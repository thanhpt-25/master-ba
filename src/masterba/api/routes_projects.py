"""Sessions, projects, intake upload, stage runs and jobs (spec 08 sections 2 and 3)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from masterba.api.auth import User
from masterba.api.deps import (
    COOKIE,
    current_user,
    project_store,
    require_role,
    state_of,
)
from masterba.api.jobs import JobBusyError
from masterba.api.routes_docs import run_summaries
from masterba.api.schemas import (
    INTAKE_NAME,
    STAGES,
    CreateProjectBody,
    LoginBody,
    RunStageBody,
)
from masterba.api.settings import MAX_UPLOAD_CHARS, Settings
from masterba.models import ProjectConfig
from masterba.models.enums import DrStatus, QuestionStatus, ReviewStage
from masterba.pipeline import (
    Resume,
    run_basic_design,
    run_brd,
    run_detail_design,
    run_srs,
    stage_summary,
)
from masterba.review import blocking_phase, phase_state
from masterba.trace_store import (
    DuplicateIdError,
    ProjectStore,
    create_project,
    document_versions,
    get_config,
    get_document,
    get_trace_links,
    list_decision_records,
    list_questions,
    list_requirements,
)
from masterba.trace_store.git import ensure_ready

router = APIRouter(prefix="/api")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
Approver = Depends(require_role("approver"))
Admin = Depends(require_role("admin"))

STAGE_DOCS: dict[str, tuple[str, ...]] = {
    "brd": ("DOC-BRD-0001",),
    "srs": ("DOC-SRS-0001",),
    "basic": ("DOC-BASIC_DESIGN-0001", "DOC-TEST_IT-0001", "DOC-TEST_ST-0001"),
    "detail": ("DOC-DETAIL_DESIGN-0001", "DOC-TEST_UT-0001"),
}
STAGE_TYPE = {"brd": "BRD", "srs": "SRS", "basic": "BASIC_DESIGN", "detail": "DETAIL_DESIGN"}
REQUIRES = {"brd": None, "srs": "brd", "basic": "srs", "detail": "basic"}


@router.post("/login")
def login(request: Request, body: LoginBody, response: Response) -> dict[str, str]:
    app = state_of(request)
    if app.throttle.locked(body.name):
        raise HTTPException(status_code=401, detail="sign-in failed")
    user = app.users.verify(body.name, body.password)
    if user is None:
        app.throttle.failure(body.name)
        raise HTTPException(status_code=401, detail="sign-in failed")
    app.throttle.success(body.name)
    response.set_cookie(
        COOKIE,
        app.signer.issue(user.name, app.settings.session_hours),
        max_age=app.settings.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"name": user.name, "role": user.role}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
    return {"name": user.name, "role": user.role}


def _project_json(settings: Settings, store: ProjectStore) -> dict[str, Any]:
    return get_config(store).model_dump(mode="json")


@router.get("/projects", dependencies=[Viewer])
def list_projects(request: Request) -> list[dict[str, Any]]:
    settings = state_of(request).settings
    if not settings.projects.exists():
        return []
    found = []
    for path in sorted(settings.projects.glob("PRJ-???")):
        if (path / "project.json").exists():
            found.append(_project_json(settings, ProjectStore(settings.projects, path.name)))
    return found


@router.post("/projects", status_code=201, dependencies=[Admin])
def new_project(request: Request, body: CreateProjectBody) -> dict[str, Any]:
    settings = state_of(request).settings
    ensure_ready(settings.root)
    config = ProjectConfig(**body.model_dump())
    try:
        store = create_project(settings.projects, config)
    except DuplicateIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _project_json(settings, store)


def _stage_status(store: ProjectStore, stage: str, running: bool) -> dict[str, Any]:
    docs = []
    for doc_id in STAGE_DOCS[stage]:
        versions = document_versions(store, doc_id)
        if versions:
            doc, _ = get_document(store, doc_id)
            docs.append({"id": doc_id, "version": versions[-1], "status": doc.status.value})
    runs = [
        r
        for r in run_summaries(store)
        if r["stage"] == STAGE_TYPE[stage] and r["trigger"] == "initial"
    ]
    last = runs[0] if runs else None
    if running:
        status = "running"
    elif len(docs) == len(STAGE_DOCS[stage]):
        status = "done"
    elif last is not None and last["status"] == "escalated":
        status = "escalated"
    else:
        status = "not_started"
    review = phase_state(store, ReviewStage(stage))
    blocked = blocking_phase(store, ReviewStage(stage))
    return {
        "stage": stage,
        "status": status,
        "documents": docs,
        "last_run": last,
        "review": review,
        "waiting_for": blocked.value if blocked else None,
    }


@router.get("/projects/{pid}", dependencies=[Viewer])
def overview(request: Request, store: Store) -> dict[str, Any]:
    app = state_of(request)
    job = app.jobs.running(store.project_id)
    stages = [
        _stage_status(store, stage, job is not None and job.kind == f"stage:{stage}")
        for stage in STAGES
    ]
    questions = [
        f"{q.id}: {q.text}" for q in list_questions(store) if q.status is QuestionStatus.OPEN
    ]
    return {
        "project": get_config(store).model_dump(mode="json"),
        "stages": stages,
        "counts": {
            "requirements": len(list_requirements(store)),
            "links": len(get_trace_links(store)),
            "open_drs": sum(
                1 for d in list_decision_records(store) if d.status is not DrStatus.CLOSED
            ),
            "open_questions": len(questions),
        },
        "job": job.to_json() if job else None,
        "open_questions": questions,
    }


@router.post("/projects/{pid}/intake", status_code=201, dependencies=[Approver])
async def upload_intake(request: Request, store: Store, file: UploadFile) -> dict[str, str]:
    name = file.filename or ""
    if not INTAKE_NAME.match(name):
        raise HTTPException(status_code=400, detail="upload a .txt or .md file with a plain name")
    raw = await file.read(MAX_UPLOAD_CHARS * 4 + 1)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="the file must be UTF-8 text") from exc
    if len(text) > MAX_UPLOAD_CHARS:
        raise HTTPException(status_code=400, detail=f"longer than {MAX_UPLOAD_CHARS} characters")
    folder = state_of(request).settings.uploads_dir / store.project_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return {"name": name}


def _stage_work(settings: Settings, store: ProjectStore, stage: str, body: RunStageBody) -> Any:
    intake_path = settings.uploads_dir / store.project_id / (body.intake or "")
    if stage == "brd" and (
        not body.intake or not INTAKE_NAME.match(body.intake) or not intake_path.exists()
    ):
        raise HTTPException(status_code=400, detail="upload an intake first and name it")

    def work() -> dict[str, Any]:
        writer = settings.llm_factory(settings.model)
        qa = settings.llm_factory(settings.qa_model) if settings.qa_model else None
        tester = settings.llm_factory(settings.test_model) if settings.test_model else None
        resume = Resume(body.resume, body.rounds) if body.resume else None
        if stage == "brd":
            result = run_brd(
                store,
                settings.templates,
                writer,
                intake_path,
                qa_llm=qa,
                reuse_intake=body.reuse_intake,
                resume=resume,
            )
        elif stage == "srs":
            result = run_srs(store, settings.templates, writer, qa_llm=qa, resume=resume)
        else:
            run = run_basic_design if stage == "basic" else run_detail_design
            result = run(
                store, settings.templates, writer, tester_llm=tester, qa_llm=qa, resume=resume
            )
        return stage_summary(result)

    return work


@router.post("/projects/{pid}/stages/{stage}/run", status_code=202, dependencies=[Approver])
def run_stage(request: Request, store: Store, stage: str, body: RunStageBody) -> dict[str, Any]:
    if stage not in STAGES:
        raise HTTPException(status_code=404, detail="no such stage")
    app = state_of(request)
    work = _stage_work(app.settings, store, stage, body)
    try:
        job = app.jobs.submit(store.project_id, f"stage:{stage}", work)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_json()


@router.get("/projects/{pid}/jobs", dependencies=[Viewer])
def project_jobs(request: Request, store: Store) -> list[dict[str, Any]]:
    return [j.to_json() for j in state_of(request).jobs.for_project(store.project_id)]


@router.get("/jobs/{job_id}", dependencies=[Viewer])
def read_job(request: Request, job_id: str) -> JSONResponse:
    job = state_of(request).jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return JSONResponse(job.to_json())
