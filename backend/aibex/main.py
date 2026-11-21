"""FastAPI app: API under /api, built frontend (if present) at /.

`create_app()` builds an app from explicit `Settings` (tests use a temp data dir) and an optional injected LLM provider
(tests use a scripted one). `app = create_app()` is what uvicorn serves. Contract: docs/api.md.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aibex import __version__
from aibex.bundles import Bundle, BundleError, BundleNotFound, BundleRegistry
from aibex.config import Settings
from aibex.query import QueryError, run_query


class QueryRequest(BaseModel):
    sql: str
    limit: int | None = None


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

    @router.post("/bundles/{bundle_id}/query")
    def bundle_query(bundle_id: str, body: QueryRequest, request: Request) -> dict:
        """Read-only single SELECT/WITH; 400 with the reason when the guard rejects it or it fails."""
        bundle = get_bundle(request, bundle_id)
        try:
            return run_query(bundle.cursor(), body.sql, body.limit)
        except QueryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    return router


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
    app.include_router(_api_router())

    if settings.frontend_dist.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def placeholder() -> str:
            return _placeholder_page()

    return app


app = create_app()
