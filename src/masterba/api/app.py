"""The FastAPI application: routes, security middleware, error mapping, static web app."""

import logging
from collections.abc import Awaitable, Callable
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from masterba.agents import QaOutputInvalidError
from masterba.api import (
    routes_docs,
    routes_drs,
    routes_knowledge,
    routes_projects,
    routes_questions,
    routes_templates,
    routes_trace,
)
from masterba.api.auth import LoginThrottle, SessionSigner, UserStore
from masterba.api.deps import AppState
from masterba.api.jobs import JobManager
from masterba.api.settings import Settings
from masterba.calibration import CalibrationError
from masterba.change import LifecycleError, PatchError
from masterba.knowledge import (
    KbCommitError,
    KbError,
    KnowledgeUnavailableError,
    SearchArgumentError,
    UnknownSourceError,
)
from masterba.knowledge.embedder import RagUnavailableError
from masterba.llm import LLMError
from masterba.rendering import RenderError
from masterba.trace_store import NotFoundError, TraceStoreError

logger = logging.getLogger(__name__)
FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(settings: Settings, frontend_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="MasterBA", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.masterba = AppState(
        settings=settings,
        users=UserStore(settings.state_dir / "users.json", settings.hash_iterations),
        signer=SessionSigner(settings.state_dir / "secret"),
        throttle=LoginThrottle(),
        jobs=JobManager(settings.state_dir / "jobs"),
    )

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.url.path.startswith("/api")
            and request.method in UNSAFE_METHODS
            and request.headers.get("X-MasterBA") != "1"
        ):
            response: Response = JSONResponse(
                {"detail": "missing X-MasterBA header"}, status_code=403
            )
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(UnknownSourceError)
    async def unknown_source(_: Request, exc: UnknownSourceError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(KnowledgeUnavailableError)
    async def kb_unavailable(_: Request, exc: KnowledgeUnavailableError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(KbCommitError)
    async def kb_commit(_: Request, exc: KbCommitError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=500)

    @app.exception_handler(KbError)
    @app.exception_handler(SearchArgumentError)
    @app.exception_handler(RagUnavailableError)
    @app.exception_handler(TraceStoreError)
    @app.exception_handler(LifecycleError)
    @app.exception_handler(CalibrationError)
    @app.exception_handler(PatchError)
    @app.exception_handler(RenderError)
    @app.exception_handler(QaOutputInvalidError)
    @app.exception_handler(LLMError)
    async def rejected(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse({"detail": "internal error"}, status_code=500)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Unauthenticated liveness check (spec 11 section 5.4); reads no project data."""
        return {"status": "ok", "version": version("masterba")}

    for module in (
        routes_projects,
        routes_docs,
        routes_trace,
        routes_drs,
        routes_questions,
        routes_knowledge,
        routes_templates,
    ):
        app.include_router(module.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def unknown_api(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "no such endpoint"}, status_code=404)

    directory = frontend_dir or FRONTEND
    app.mount("/", StaticFiles(directory=directory, html=True, check_dir=False), name="web")
    return app
