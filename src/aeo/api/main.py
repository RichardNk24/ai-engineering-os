from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aeo.analytics.service import engineering_analytics
from aeo.api.schemas import RunRead, TaskRead
from aeo.db.models import EngineeringRun
from aeo.db.session import create_session_factory
from aeo.tasks.service import get_task, list_tasks

app = FastAPI(
    title="AI Engineering OS",
    version="0.3.0",
    description="Observable engineering workflow and agent orchestration platform.",
)


def project_root() -> Path:
    return Path.cwd().resolve()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0"}


@app.get("/runs", response_model=list[RunRead])
def list_runs(limit: int = Query(default=50, ge=1, le=500)) -> list[EngineeringRun]:
    session_factory = create_session_factory(project_root())
    with session_factory() as session:
        rows = session.scalars(
            select(EngineeringRun)
            .options(
                selectinload(EngineeringRun.events),
                selectinload(EngineeringRun.git_snapshot),
                selectinload(EngineeringRun.environment),
            )
            .order_by(EngineeringRun.started_at.desc())
            .limit(limit)
        ).all()
        return list(rows)


@app.get("/tasks", response_model=list[TaskRead])
def tasks(limit: int = Query(default=50, ge=1, le=500)) -> list[TaskRead]:
    return [TaskRead(**asdict(task)) for task in list_tasks(project_root(), limit=limit)]


@app.get("/tasks/{task_id}", response_model=TaskRead)
def task_detail(task_id: str) -> TaskRead:
    try:
        task = get_task(project_root(), task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Engineering task not found")
    return TaskRead(**asdict(task))


@app.get("/stats")
def stats() -> dict[str, object]:
    return engineering_analytics(project_root())
