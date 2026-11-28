"""Sessions, projects, intake upload, stage runs and jobs (spec 08 sections 2 and 3)."""

import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from masterba.api.auth import User
from masterba.api.deps import (
    COOKIE,
    AppState,
    audit,
    current_user,
    metered,
    project_store,
    require_quota,
    require_role,
    state_of,
)
from masterba.api.jobs import JobBusyError
from masterba.api.routes_docs import run_summaries
from masterba.api.schemas import (
    INTAKE_NAME,
    STAGES,
    CreateProjectBody,
    GuardSettingsBody,
    LoginBody,
    ProjectBudgetBody,
    PropagationModeBody,
    RunStageBody,
)
from masterba.api.settings import MAX_UPLOAD_CHARS
from masterba.guard import UploadScan, clean_terms, scan_text
from masterba.intake import CONVERTED_SUFFIXES, intake_name, intake_text
from masterba.knowledge.safety import MAX_FILE_BYTES, check_upload
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
    InvalidDocumentError,
    ProjectStore,
    create_project,
    document_versions,
    get_config,
    get_document,
    get_trace_links,
    list_decision_records,
    list_questions,
    list_requirements,
    set_config,
)
from masterba.trace_store.git import ensure_ready

router = APIRouter(prefix="/api")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
Approver = Depends(require_role("approver"))
Admin = Depends(require_role("admin"))
Signed = Annotated[User, Depends(require_role("approver"))]
Me = Annotated[User, Depends(current_user)]
ProjectAdminUser = Annotated[User, Depends(require_role("admin"))]

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
        audit(request, "anonymous", "auth.login_failed", target=body.name, reason="locked")
        raise HTTPException(status_code=401, detail="sign-in failed")
    user = app.users.verify(body.name, body.password)
    if user is None:
        app.throttle.failure(body.name)
        audit(request, "anonymous", "auth.login_failed", target=body.name)
        raise HTTPException(status_code=401, detail="sign-in failed")
    app.throttle.success(body.name)
    app.users.touch_login(user.name)
    audit(request, user.name, "auth.login", target=user.name)
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
def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(COOKIE)
    session = state_of(request).signer.session(token) if token else None
    if session is not None:
        audit(request, session.name, "auth.logout", target=session.name)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: Me) -> dict[str, Any]:
    """Who is signed in and how much of each usage window is left (spec 23 section 8)."""
    usage = state_of(request).usage.status(user.name)
    return {"name": user.name, "role": user.role, "usage": [w.to_json() for w in usage]}


def _project_json(app: AppState, store: ProjectStore, user: User) -> dict[str, Any]:
    entry = app.access.entry(store.project_id) or {}
    return {
        **get_config(store).model_dump(mode="json"),
        "owner": entry.get("owner"),
        "my_role": app.access.role_of(store.project_id, user),
    }


@router.get("/projects")
def list_projects(request: Request, user: Me) -> list[dict[str, Any]]:
    """Only the projects the user owns, was given, or every project for an admin."""
    app = state_of(request)
    return [
        _project_json(app, ProjectStore(app.settings.projects, pid), user)
        for pid in app.access.visible(user)
    ]


@router.post("/projects", status_code=201)
def new_project(request: Request, body: CreateProjectBody, user: Signed) -> dict[str, Any]:
    """An approver or admin creates a project and becomes its owner (spec 23 section 2)."""
    app = state_of(request)
    settings = app.settings
    ensure_ready(settings.root)
    if not app.templates.sees(body.company_id, user):
        raise HTTPException(status_code=400, detail=f"no template set {body.company_id}")
    config = ProjectConfig(**body.model_dump())
    try:
        store = create_project(settings.projects, config)
    except DuplicateIdError as exc:
        # Do not tell whose project it is; it may not be visible to this user.
        raise HTTPException(
            status_code=400, detail=f"{body.project_id} is taken; choose another project id"
        ) from exc
    app.access.create(store.project_id, user.name)
    audit(request, user.name, "project.create", project=store.project_id, target=store.project_id)
    return _project_json(app, store, user)


@router.post("/projects/{pid}/settings/token-budget", dependencies=[Admin])
def update_token_budget(store: Store, body: ProjectBudgetBody) -> dict[str, Any]:
    current = get_config(store)
    updated = current.model_copy(update={"team_token_budget": body.team_token_budget})
    set_config(store, ProjectConfig.model_validate(updated.model_dump()))
    return get_config(store).model_dump(mode="json")


@router.post("/projects/{pid}/settings/propagation-mode", dependencies=[Admin])
def update_propagation_mode(store: Store, body: PropagationModeBody) -> dict[str, Any]:
    updated = get_config(store).model_copy(update={"propagation_mode": body.propagation_mode})
    set_config(store, ProjectConfig.model_validate(updated.model_dump()))
    return get_config(store).model_dump(mode="json")


@router.post("/projects/{pid}/settings/guard")
def update_guard(
    request: Request, store: Store, body: GuardSettingsBody, user: ProjectAdminUser
) -> dict[str, Any]:
    """Masking settings (spec 30 section 2.3); only a global admin may switch masking off."""
    current = get_config(store)
    if current.pii_masking and not body.pii_masking and user.role != "admin":
        raise HTTPException(status_code=403, detail="only an administrator may switch masking off")
    terms = clean_terms(body.masking_terms)
    updated = current.model_copy(update={"pii_masking": body.pii_masking, "masking_terms": terms})
    set_config(store, ProjectConfig.model_validate(updated.model_dump()))
    audit(
        request,
        user.name,
        "project.guard",
        project=store.project_id,
        target=store.project_id,
        pii_masking=body.pii_masking,
        terms=len(terms),
    )
    return get_config(store).model_dump(mode="json")


def stage_status(store: ProjectStore, stage: str, running: bool) -> dict[str, Any]:
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
    elif last is not None and last["status"] in {"escalated", "waiting_for_input"}:
        status = last["status"]
    elif len(docs) == len(STAGE_DOCS[stage]):
        status = "done"
    else:
        status = "not_started"
    review = phase_state(store, ReviewStage(stage))
    blocked = blocking_phase(store, ReviewStage(stage))
    types = {doc_id.split("-")[1] for doc_id in STAGE_DOCS[stage]}
    asked = sum(
        1
        for q in list_questions(store)
        if q.status is QuestionStatus.OPEN and q.stage.value in types
    )
    return {
        "stage": stage,
        "status": status,
        "documents": docs,
        "last_run": last,
        "review": review,
        "waiting_for": blocked.value if blocked else None,
        "open_questions": asked,
    }


@router.get("/projects/{pid}")
def overview(request: Request, store: Store, user: Annotated[User, Viewer]) -> dict[str, Any]:
    app = state_of(request)
    job = app.jobs.running(store.project_id)
    stages = [
        stage_status(store, stage, job is not None and job.kind == f"stage:{stage}")
        for stage in STAGES
    ]
    questions = [
        f"{q.id}: {q.text}" for q in list_questions(store) if q.status is QuestionStatus.OPEN
    ]
    return {
        "project": _project_json(app, store, user),
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
        "pending_drs": [
            {"id": d.id, "description": d.description}
            for d in list_decision_records(store)
            if d.status is DrStatus.APPROVED and d.affected_documents
        ],
    }


def _converted(folder: Path, name: str, data: bytes) -> str:
    """The Markdown text of an uploaded Word, PDF or Excel intake; the original is not kept."""
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as scratch:
        original = Path(scratch) / f"upload{Path(name).suffix.lower()}"
        original.write_bytes(data)
        try:
            return intake_text(original)
        except InvalidDocumentError as exc:
            detail = str(exc).replace(original.name, name)
            raise HTTPException(status_code=400, detail=detail) from exc


def _scanned(text: str) -> UploadScan:
    """Spec 30 section 3.2: a secret refuses the intake; personal data is reported."""
    scan = scan_text(text)
    refusal = scan.refusal()
    if refusal is not None:
        raise HTTPException(status_code=400, detail=refusal)
    return scan


@router.post("/projects/{pid}/intake", status_code=201, dependencies=[Approver])
async def upload_intake(request: Request, store: Store, file: UploadFile) -> dict[str, Any]:
    """Store an intake for the BRD run; Word, PDF and Excel are converted at once (spec 19)."""
    name = file.filename or ""
    folder = state_of(request).settings.uploads_dir / store.project_id
    if Path(name).suffix.lower() in CONVERTED_SUFFIXES:
        data = await file.read(MAX_FILE_BYTES + 1)
        refusals = check_upload(name, data)
        if refusals:
            raise HTTPException(status_code=400, detail=refusals[0].message)
        stored = intake_name(name)
        text = _converted(folder, name, data)
        if len(text) > MAX_UPLOAD_CHARS:
            raise HTTPException(
                status_code=400, detail=f"longer than {MAX_UPLOAD_CHARS} characters"
            )
        scan = _scanned(text)
        (folder / stored).write_text(text, encoding="utf-8")
        return {"name": stored, "converted_from": name, "findings": scan.report()}
    if not INTAKE_NAME.match(name):
        raise HTTPException(
            status_code=400,
            detail="upload a .txt, .md, .docx, .pdf or .xlsx file; a text file needs a plain name",
        )
    raw = await file.read(MAX_UPLOAD_CHARS * 4 + 1)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="the file must be UTF-8 text") from exc
    if len(text) > MAX_UPLOAD_CHARS:
        raise HTTPException(status_code=400, detail=f"longer than {MAX_UPLOAD_CHARS} characters")
    scan = _scanned(text)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return {"name": name, "findings": scan.report()}


def _stage_work(
    app: AppState, user: User, store: ProjectStore, stage: str, body: RunStageBody
) -> Any:
    settings = app.settings
    llm_factory = metered(app, user, store.project_id, f"stage:{stage}")
    intake_path = settings.uploads_dir / store.project_id / (body.intake or "")
    if stage == "brd" and (
        not body.intake or not INTAKE_NAME.match(body.intake) or not intake_path.exists()
    ):
        raise HTTPException(status_code=400, detail="upload an intake first and name it")

    def work() -> dict[str, Any]:
        writer = llm_factory(settings.model)
        qa = llm_factory(settings.qa_model) if settings.qa_model else None
        tester = llm_factory(settings.test_model) if settings.test_model else None
        resume = (
            Resume(body.resume, body.rounds if body.rounds is not None else 1)
            if body.resume
            else None
        )
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


@router.post("/projects/{pid}/stages/{stage}/run", status_code=202)
def run_stage(
    request: Request, store: Store, stage: str, body: RunStageBody, user: Signed
) -> dict[str, Any]:
    if stage not in STAGES:
        raise HTTPException(status_code=404, detail="no such stage")
    app = state_of(request)
    runs = [
        r
        for r in run_summaries(store)
        if r["stage"] == STAGE_TYPE[stage] and r["trigger"] == "initial"
    ]
    if body.resume:
        selected = next((r for r in runs if r["run_id"] == body.resume), None)
        if selected is None or selected["status"] not in {"escalated", "waiting_for_input"}:
            raise HTTPException(status_code=409, detail="run is not resumable")
        if selected["waiting_questions"]:
            ids = ", ".join(q["id"] for q in selected["waiting_questions"])
            raise HTTPException(
                status_code=409, detail=f"answer or withdraw blocker questions first: {ids}"
            )
    else:
        waiting = next(
            (r for r in runs if r["status"] == "waiting_for_input" and r["waiting_questions"]), None
        )
        if waiting:
            ids = ", ".join(q["id"] for q in waiting["waiting_questions"])
            raise HTTPException(
                status_code=409,
                detail=f"resume {waiting['run_id']} after answering blocker questions: {ids}",
            )
    require_quota(app, user)
    work = _stage_work(app, user, store, stage, body)
    try:
        job = app.jobs.submit(store.project_id, f"stage:{stage}", work, user.name)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_json()


@router.get("/projects/{pid}/jobs", dependencies=[Viewer])
def project_jobs(request: Request, store: Store) -> list[dict[str, Any]]:
    return [j.to_json() for j in state_of(request).jobs.for_project(store.project_id)]


@router.get("/jobs/{job_id}")
def read_job(request: Request, job_id: str, user: Me) -> JSONResponse:
    app = state_of(request)
    job = app.jobs.get(job_id)
    if job is None or app.access.role_of(job.project_id, user) is None:
        raise HTTPException(status_code=404, detail="no such job")
    return JSONResponse(job.to_json())
