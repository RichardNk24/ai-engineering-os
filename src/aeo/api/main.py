from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aeo.api.schemas import RunRead
from aeo.db.models import EngineeringRun
from aeo.db.session import create_session_factory
from aeo.telemetry.service import stats as collect_stats

app = FastAPI(
    title="AI Engineering OS",
    version="0.2.0",
    description="Observable engineering workflow and agent orchestration platform.",
)


def project_root() -> Path:
    return Path.cwd().resolve()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/runs", response_model=list[RunRead])
def list_runs(limit: int = 50) -> list[EngineeringRun]:
    session_factory = create_session_factory(project_root())
    with session_factory() as session:
        rows = session.scalars(
            select(EngineeringRun)
            .options(
                selectinload(EngineeringRun.events),
                selectinload(EngineeringRun.git_snapshot),
            )
            .order_by(EngineeringRun.started_at.desc())
            .limit(limit)
        ).all()
        return list(rows)


@app.get("/stats")
def stats() -> dict:
    return collect_stats(project_root())
