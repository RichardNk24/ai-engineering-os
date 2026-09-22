"""Read-only local control plane; mutations remain explicit CLI actions."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import __version__, storage
from .gitops import repo_root
from .safety import WorkbenchError


def create_router(root: Path, token: str) -> APIRouter:
    if len(token) < 24:
        raise ValueError("AEO_API_TOKEN must contain at least 24 characters.")
    root = repo_root(root)
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    router = APIRouter(prefix="/workbench", dependencies=[Depends(authorize)])

    @router.get("/health")
    def health():
        return {"version": __version__, "mode": "local-read-only"}

    @router.get("/runs")
    def runs(limit: int = Query(20, ge=1, le=200)):
        return {"runs": storage.history(root, limit)}

    @router.get("/runs/{run_id}")
    def run(run_id: str):
        try:
            return storage.get(root, run_id)
        except WorkbenchError as exc:
            raise HTTPException(404, "Run not found") from exc

    @router.get("/runs/{run_id}/events")
    def events(run_id: str):
        try:
            return {"events": storage.events(root, run_id)}
        except WorkbenchError as exc:
            raise HTTPException(404, "Run not found") from exc

    @router.get("/runs/{run_id}/report")
    def report(run_id: str):
        from .report import build_report

        try:
            return build_report(root, run_id)
        except WorkbenchError as exc:
            raise HTTPException(404, "Run not found") from exc

    return router


def create_app(root: Path, token: str) -> FastAPI:
    app = FastAPI(
        title="AEO Workbench", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(create_router(root, token))
    return app
