from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from aeo.checks.runner import run_all_checks
from aeo.db.models import EngineeringTask
from aeo.db.session import create_session_factory
from aeo.domain.enums import TaskStatus
from aeo.git.service import collect_git_context


@dataclass(slots=True)
class TaskSummary:
    id: str
    title: str
    status: str
    duration_ms: float | None
    start_branch: str | None
    start_commit_sha: str | None
    end_branch: str | None
    end_commit_sha: str | None
    changed_files: int
    insertions: int
    deletions: int
    validation_run_id: str | None


def _to_summary(task: EngineeringTask) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        title=task.title,
        status=task.status,
        duration_ms=task.duration_ms,
        start_branch=task.start_branch,
        start_commit_sha=task.start_commit_sha,
        end_branch=task.end_branch,
        end_commit_sha=task.end_commit_sha,
        changed_files=task.changed_files,
        insertions=task.insertions,
        deletions=task.deletions,
        validation_run_id=task.validation_run_id,
    )


def get_active_task(root: Path) -> TaskSummary | None:
    session_factory = create_session_factory(root)

    with session_factory() as session:
        task = session.scalar(
            select(EngineeringTask)
            .where(EngineeringTask.status == TaskStatus.ACTIVE)
            .order_by(EngineeringTask.started_at.desc())
        )
        return _to_summary(task) if task is not None else None


def start_task(root: Path, title: str) -> TaskSummary:
    existing = get_active_task(root)
    if existing is not None:
        raise RuntimeError(
            f"Task {existing.id} is already active: {existing.title}. "
            "Finish or cancel it before starting another."
        )

    git_context = collect_git_context(root)
    session_factory = create_session_factory(root)

    with session_factory() as session:
        task = EngineeringTask(
            title=title,
            status=TaskStatus.ACTIVE,
            project_root=str(root),
            start_branch=git_context.branch,
            start_commit_sha=git_context.commit_sha,
        )
        session.add(task)
        session.commit()
        return _to_summary(task)


def finish_task(root: Path, *, run_validation: bool = True) -> TaskSummary:
    session_factory = create_session_factory(root)

    with session_factory() as session:
        task = session.scalar(
            select(EngineeringTask)
            .where(EngineeringTask.status == TaskStatus.ACTIVE)
            .order_by(EngineeringTask.started_at.desc())
        )

        if task is None:
            raise RuntimeError("No active AEO task found.")

        validation_run_id: str | None = None
        if run_validation:
            results = run_all_checks(root)
            # The check runner records exactly one run. Resolve the latest check run.
            from aeo.db.models import EngineeringRun

            latest_run = session.scalar(
                select(EngineeringRun)
                .where(EngineeringRun.command == "check")
                .order_by(EngineeringRun.started_at.desc())
            )
            if latest_run is not None:
                validation_run_id = latest_run.id

            # Explicitly keep result evaluation here for future policy hooks.
            _ = all(result.passed for result in results)

        git_context = collect_git_context(root)
        completed_at = datetime.now(UTC)

        task.status = TaskStatus.COMPLETED
        task.completed_at = completed_at
        task.duration_ms = (completed_at - task.started_at).total_seconds() * 1000
        task.end_branch = git_context.branch
        task.end_commit_sha = git_context.commit_sha
        task.changed_files = git_context.changed_files
        task.insertions = git_context.insertions
        task.deletions = git_context.deletions
        task.validation_run_id = validation_run_id

        session.commit()
        return _to_summary(task)


def cancel_task(root: Path) -> TaskSummary:
    session_factory = create_session_factory(root)

    with session_factory() as session:
        task = session.scalar(
            select(EngineeringTask)
            .where(EngineeringTask.status == TaskStatus.ACTIVE)
            .order_by(EngineeringTask.started_at.desc())
        )

        if task is None:
            raise RuntimeError("No active AEO task found.")

        completed_at = datetime.now(UTC)
        task.status = TaskStatus.CANCELLED
        task.completed_at = completed_at
        task.duration_ms = (completed_at - task.started_at).total_seconds() * 1000
        session.commit()
        return _to_summary(task)
