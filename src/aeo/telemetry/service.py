from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy import func, select

from aeo.db.models import EngineeringEvent, EngineeringRun, GitSnapshot
from aeo.db.session import create_session_factory
from aeo.domain.enums import EventType, RunStatus
from aeo.git.service import collect_git_context


class RunRecorder:
    def __init__(self, project_root: Path, command: str) -> None:
        self.project_root = project_root
        self.command = command
        self.session_factory = create_session_factory(project_root)
        self.run: EngineeringRun | None = None
        self._started_perf: float | None = None

    def start(self) -> EngineeringRun:
        self._started_perf = perf_counter()
        git_context = collect_git_context(self.project_root)

        with self.session_factory() as session:
            run = EngineeringRun(
                command=self.command,
                status=RunStatus.RUNNING,
                project_root=str(self.project_root),
            )
            session.add(run)
            session.flush()

            session.add(
                EngineeringEvent(
                    run_id=run.id,
                    event_type=EventType.RUN_STARTED,
                    message=f"{self.command} started",
                )
            )

            if git_context.is_repository:
                session.add(
                    GitSnapshot(
                        run_id=run.id,
                        branch=git_context.branch,
                        commit_sha=git_context.commit_sha,
                        dirty_worktree=git_context.dirty_worktree,
                        changed_files=git_context.changed_files,
                        insertions=git_context.insertions,
                        deletions=git_context.deletions,
                        untracked_files=git_context.untracked_files,
                    )
                )

            session.commit()
            self.run = run
            return run

    def event(
        self,
        event_type: EventType,
        *,
        stage: str | None = None,
        message: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        if self.run is None:
            raise RuntimeError("Run has not been started.")

        with self.session_factory() as session:
            session.add(
                EngineeringEvent(
                    run_id=self.run.id,
                    event_type=event_type,
                    stage=stage,
                    message=message,
                    duration_ms=duration_ms,
                )
            )
            session.commit()

    def complete(self, status: RunStatus) -> None:
        if self.run is None or self._started_perf is None:
            raise RuntimeError("Run has not been started.")

        duration_ms = (perf_counter() - self._started_perf) * 1000

        with self.session_factory() as session:
            run = session.get(EngineeringRun, self.run.id)
            assert run is not None
            run.status = status
            run.completed_at = datetime.now(UTC)
            run.duration_ms = duration_ms
            session.add(
                EngineeringEvent(
                    run_id=run.id,
                    event_type=EventType.RUN_COMPLETED,
                    message=f"run completed with status={status}",
                    duration_ms=duration_ms,
                )
            )
            session.commit()


def stats(project_root: Path) -> dict:
    session_factory = create_session_factory(project_root)

    with session_factory() as session:
        total = session.scalar(select(func.count()).select_from(EngineeringRun)) or 0
        passed = session.scalar(
            select(func.count())
            .select_from(EngineeringRun)
            .where(EngineeringRun.status == RunStatus.PASSED)
        ) or 0
        failed = session.scalar(
            select(func.count())
            .select_from(EngineeringRun)
            .where(EngineeringRun.status == RunStatus.FAILED)
        ) or 0
        avg_duration = session.scalar(
            select(func.avg(EngineeringRun.duration_ms))
            .where(EngineeringRun.duration_ms.is_not(None))
        )

    return {
        "runs": total,
        "passed": passed,
        "failed": failed,
        "success_rate": round((passed / total) * 100, 2) if total else 0.0,
        "average_duration_ms": round(float(avg_duration or 0), 2),
    }
