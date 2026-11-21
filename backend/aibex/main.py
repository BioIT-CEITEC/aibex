"""FastAPI app: API under /api, built frontend (if present) at /.

`create_app()` builds an app from explicit `Settings` (tests use a temp data dir) and an optional injected LLM provider
(tests use a scripted one). `app = create_app()` is what uvicorn serves. Contract: docs/api.md.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aibex import __version__
from aibex.bundles import Bundle, BundleError, BundleNotFound, BundleRegistry
from aibex.config import Settings
from aibex.default_view import default_view
from aibex.panel_data import PanelDataUnsupported, PanelNotFound, panel_data
from aibex.query import QueryError, run_query
from aibex.sessions import NothingToUndo, PatchError, Session, SessionNotFound, SessionStore
from aibex.spec import parse_spec
from aibex.validate import validate_spec


class QueryRequest(BaseModel):
    sql: str
    limit: int | None = None


class SessionRequest(BaseModel):
    bundle: str


class PatchRequest(BaseModel):
    patch: Any
    summary: str | None = None


class PanelDataRequest(BaseModel):
    panel_id: str
    selection: list[Any] | None = None  # used by widget inputs ($selected, T40a); plot/table panels ignore it


class StepsRequest(BaseModel):
    steps: int = Field(default=1, ge=1, le=1000)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _api_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health(request: Request) -> dict:
        s = get_settings(request)
        return {
            "status": "ok",
            "version": __version__,
            "llm_provider": s.llm_provider,
            "llm_configured": s.llm_configured,
            "llm_models": {"fast": s.llm_model_fast, "code": s.llm_model_code},
            "data_dir_exists": s.data_dir.exists(),
        }

    @router.get("/bundles")
    def bundles(request: Request) -> list[dict]:
        return get_registry(request).list()

    @router.get("/bundles/{bundle_id}/schema")
    def bundle_schema(bundle_id: str, request: Request) -> dict:
        return get_bundle(request, bundle_id).schema()

    @router.get("/bundles/{bundle_id}/default-view")
    def bundle_default_view(bundle_id: str, request: Request) -> dict:
        """The bundle's `default_view` file if valid, else a generated spec (always valid)."""
        return default_view(get_bundle(request, bundle_id))

    @router.post("/bundles/{bundle_id}/query")
    def bundle_query(bundle_id: str, body: QueryRequest, request: Request) -> dict:
        """Read-only single SELECT/WITH; 400 with the reason when the guard rejects it or it fails."""
        bundle = get_bundle(request, bundle_id)
        try:
            return run_query(bundle.cursor(), body.sql, body.limit)
        except QueryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.post("/validate-spec")
    def validate_spec_endpoint(request: Request, data: Any = Body(...)) -> dict:  # noqa: B008
        """Structural + semantic validation against the spec's bundle; always 200 `{valid, errors}`."""
        spec, errors = parse_spec(data)
        if spec is None:
            return {"valid": False, "errors": errors}
        try:
            bundle = get_registry(request).get(spec.bundle)
        except BundleNotFound:
            return {"valid": False, "errors": [f"bundle: unknown bundle {spec.bundle!r}"]}
        except BundleError as exc:
            return {"valid": False, "errors": [f"bundle: bundle {spec.bundle!r} cannot be loaded: {exc}"]}
        _, errors = validate_spec(data, bundle)
        return {"valid": not errors, "errors": errors}

    @router.post("/sessions")
    def create_session(body: SessionRequest, request: Request) -> dict:
        """New in-memory session starting from the bundle's default view (version 0, history source `init`)."""
        bundle = get_bundle(request, body.bundle)
        registry = get_registry(request)
        s = get_sessions(request).create(bundle.id, default_view(bundle), registry.get)
        return {"session_id": s.session_id, "spec": s.spec, "version": s.version}

    @router.get("/sessions/{sid}")
    def get_session_state(sid: str, request: Request) -> dict:
        return get_session(request, sid).state()

    @router.post("/sessions/{sid}/patch")
    def patch_session(sid: str, body: PatchRequest, request: Request) -> dict:
        """Apply a validated JSON Patch as source `user`; 422 `{detail: {errors}}` and no change when invalid."""
        s = get_session(request, sid)
        try:
            with s.lock:
                spec = s.apply_patch(body.patch, body.summary, source="user")
                return {"spec": spec, "version": s.version}
        except PatchError as exc:
            raise HTTPException(status_code=422, detail={"errors": exc.errors}) from None

    @router.post("/sessions/{sid}/undo")
    def undo_session(sid: str, request: Request, body: StepsRequest | None = None) -> dict:
        return _move(request, sid, "undo", (body or StepsRequest()).steps)

    @router.post("/sessions/{sid}/redo")
    def redo_session(sid: str, request: Request, body: StepsRequest | None = None) -> dict:
        return _move(request, sid, "redo", (body or StepsRequest()).steps)

    @router.post("/sessions/{sid}/panel-data")
    def session_panel_data(sid: str, body: PanelDataRequest, request: Request) -> dict:
        """Rows of one panel of the current spec with filters applied (max 5000); unknown panel 404."""
        s = get_session(request, sid)
        with s.lock:
            data = s.spec
        spec, errors = parse_spec(data)
        if spec is None:  # cannot happen for a stored (validated) spec; never crash on it
            raise HTTPException(status_code=500, detail="; ".join(errors))
        try:
            return panel_data(spec, s.bundle, body.panel_id)
        except PanelNotFound:
            raise HTTPException(status_code=404, detail=f"unknown panel {body.panel_id!r}") from None
        except PanelDataUnsupported as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from None
        except ValueError as exc:  # PanelDataError, ExprError
            raise HTTPException(status_code=400, detail=str(exc)) from None

    return router


def _move(request: Request, sid: str, direction: str, steps: int) -> dict:
    """Undo/redo by `steps` (clamped to what is available); 409 when there is nothing to undo/redo."""
    s = get_session(request, sid)
    try:
        with s.lock:
            spec = s.undo(steps) if direction == "undo" else s.redo(steps)
            return {"spec": spec, "version": s.version}
    except NothingToUndo as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def get_sessions(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_session(request: Request, sid: str) -> Session:
    try:
        return get_sessions(request).get(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail=f"unknown session {sid!r}") from None


def get_registry(request: Request) -> BundleRegistry:
    return request.app.state.bundles


def get_bundle(request: Request, bundle_id: str) -> Bundle:
    """Loaded bundle or HTTP error: 404 unknown id, 500 with the reason when the bundle cannot be loaded."""
    try:
        return get_registry(request).get(bundle_id)
    except BundleNotFound:
        raise HTTPException(status_code=404, detail=f"unknown bundle {bundle_id!r}") from None
    except BundleError as exc:
        raise HTTPException(status_code=500, detail=f"bundle {bundle_id!r} cannot be loaded: {exc}") from None


def _placeholder_page() -> str:
    return (
        "<!doctype html><html><head><title>Aibex View</title></head>"
        "<body style='font-family:sans-serif;max-width:40rem;margin:4rem auto'>"
        "<h1>Aibex View</h1><p>Backend is running. The frontend has not been built yet.</p>"
        "<p>See <a href='/api/health'>/api/health</a> and <a href='/api/bundles'>/api/bundles</a>.</p>"
        "</body></html>"
    )


def create_app(settings: Settings | None = None, llm_provider: Any | None = None) -> FastAPI:
    """Build the app. An injected `llm_provider` (an `LLMProvider`, docs/api.md) wins over `settings.llm_provider`.

    Provider construction from settings (OpenAICompatibleProvider / FakeProvider) is added with the provider
    module (tasks T21a/T21b); until then `app.state.llm_provider` is only set when one is injected.
    """
    settings = settings or Settings()
    app = FastAPI(title="Aibex View", version=__version__)
    app.state.settings = settings
    app.state.llm_provider = llm_provider
    app.state.bundles = BundleRegistry(settings.data_dir)
    app.state.sessions = SessionStore()
    app.include_router(_api_router())

    if settings.frontend_dist.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def placeholder() -> str:
            return _placeholder_page()

    return app


app = create_app()
