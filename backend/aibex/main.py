"""FastAPI app: API under /api, built frontend (if present) at /."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from aibex import __version__
from aibex.bundles import list_bundles
from aibex.config import settings

app = FastAPI(title="Aibex View", version=__version__)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "llm_configured": settings.llm_configured,
        "llm_models": {"fast": settings.llm_model_fast, "code": settings.llm_model_code},
        "data_dir_exists": settings.data_dir.exists(),
    }


@app.get("/api/bundles")
def bundles() -> list[dict]:
    return list_bundles(settings.data_dir)


if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
else:

    @app.get("/", response_class=HTMLResponse)
    def placeholder() -> str:
        return (
            "<!doctype html><html><head><title>Aibex View</title></head>"
            "<body style='font-family:sans-serif;max-width:40rem;margin:4rem auto'>"
            "<h1>Aibex View</h1><p>Backend is running. The frontend has not been built yet.</p>"
            "<p>See <a href='/api/health'>/api/health</a> and <a href='/api/bundles'>/api/bundles</a>.</p>"
            "</body></html>"
        )
