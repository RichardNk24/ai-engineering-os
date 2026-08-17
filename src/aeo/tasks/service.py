from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aeo.checks.runner import create_quality_run, run_all_checks
from aeo.db.models import (
    EngineeringEvent,
    EngineeringRun,
    EngineeringTask,
    TaskFinalization,
    TaskValidationAttempt,
)
from aeo.db.session import create_session_factory
from aeo.domain.enums import FinalizationStatus, RunStatus, TaskStatus
from aeo.git.service import collect_git_context


@dataclass(slots=True)
class TaskSummary:
    id: str
    title: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None
    start_branch: str | None
    start_commit_sha: str | None
    end_branch: str | None
    end_commit_sha: str | None
    changed_files: int
    insertions: int
    deletions: int
    validation_run_id: str | None
    validation_attempts: int = 0
    validation_status: str | None = None
    validation_duration_ms: float | None = None


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps read from SQLite to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validation_metadata(
    session: Session,
    task: EngineeringTask,
) -> tuple[int, str | None, float | None]:
    attempts = session.scalar(
        select(func.count())
        .select_from(TaskValidationAttempt)
        .where(TaskValidationAttempt.task_id == task.id)
    ) or 0

    validation_run_id = task.validation_run_id
    if validation_run_id is None and task.finalization is not None:
        validation_run_id = task.finalization.validation_run_id

    if validation_run_id is None:
        return attempts, None, None

    run = session.get(EngineeringRun, validation_run_id)
    if run is None:
        return attempts, None, None
    return attempts, run.status, run.duration_ms


def _to_summary(session: Session, task: EngineeringTask) -> TaskSummary:
    attempts, validation_status, validation_duration_ms = _validation_metadata(session, task)
    return TaskSummary(
        id=task.id,
        title=task.title,
        status=task.status,
        started_at=_as_utc(task.started_at),
        completed_at=_as_utc(task.completed_at) if task.completed_at else None,
        duration_ms=task.duration_ms,
        start_branch=task.start_branch,
        start_commit_sha=task.start_commit_sha,
        end_branch=task.end_branch,
        end_commit_sha=task.end_commit_sha,
        changed_files=task.changed_files,
        insertions=task.insertions,
        deletions=task.deletions,
        validation_run_id=validation_run_id_for(task),
        validation_attempts=attempts,
        validation_status=validation_status,
        validation_duration_ms=validation_duration_ms,
    )


def validation_run_id_for(task: EngineeringTask) -> str | None:
    if task.validation_run_id:
        return task.validation_run_id
    if task.finalization is not None:
        return task.finalization.validation_run_id
    return None


def get_active_task(root: Path) -> TaskSummary | None:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        task = session.scalar(
            select(EngineeringTask)
            .where(EngineeringTask.status == TaskStatus.ACTIVE)
            .order_by(EngineeringTask.started_at.desc())
        )
        return _to_summary(session, task) if task is not None else None


def list_tasks(root: Path, *, limit: int = 20) -> list[TaskSummary]:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        tasks = session.scalars(
            select(EngineeringTask).order_by(EngineeringTask.started_at.desc()).limit(limit)
        ).all()
        return [_to_summary(session, task) for task in tasks]


def get_task(root: Path, task_id: str) -> TaskSummary | None:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        task = session.get(EngineeringTask, task_id)
        if task is not None:
            return _to_summary(session, task)

        matches = session.scalars(
            select(EngineeringTask)
            .where(EngineeringTask.id.like(f"{task_id}%"))
            .limit(2)
        ).all()
        if len(matches) > 1:
            raise RuntimeError(f"Task ID prefix is ambiguous: {task_id}")
        return _to_summary(session, matches[0]) if matches else None


def get_task_validation_events(root: Path, task_id: str) -> list[EngineeringEvent]:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        run_ids = session.scalars(
            select(TaskValidationAttempt.run_id)
            .where(TaskValidationAttempt.task_id == task_id)
            .order_by(TaskValidationAttempt.attempt_number)
        ).all()
        if not run_ids:
            task = session.get(EngineeringTask, task_id)
            legacy_run_id = task.validation_run_id if task is not None else None
            run_ids = [legacy_run_id] if legacy_run_id else []
        if not run_ids:
            return []
        return list(
            session.scalars(
                select(EngineeringEvent)
                .where(EngineeringEvent.run_id.in_(run_ids))
                .order_by(EngineeringEvent.created_at)
            ).all()
        )


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
        return _to_summary(session, task)


def _get_or_create_finalization(
    session: Session,
    task: EngineeringTask,
) -> TaskFinalization:
    finalization = session.scalar(
        select(TaskFinalization).where(TaskFinalization.task_id == task.id)
    )
    if finalization is None:
        finalization = TaskFinalization(
            task_id=task.id,
            status=FinalizationStatus.STARTED,
            attempts=0,
        )
        session.add(finalization)
        session.commit()
        session.refresh(finalization)
    return finalization


def _prepare_validation_run(root: Path, task_id: str, finalization_id: int) -> str:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        finalization = session.get(TaskFinalization, finalization_id)
        assert finalization is not None

        if finalization.validation_run_id:
            existing_run = session.get(EngineeringRun, finalization.validation_run_id)
            if existing_run is not None and existing_run.status == RunStatus.RUNNING:
                return existing_run.id
            if existing_run is not None and existing_run.status == RunStatus.PASSED:
                return existing_run.id

        run_id = create_quality_run(root)
        finalization.validation_run_id = run_id
        finalization.status = FinalizationStatus.STARTED
        finalization.attempts += 1
        session.add(
            TaskValidationAttempt(
                task_id=task_id,
                run_id=run_id,
                attempt_number=finalization.attempts,
            )
        )
        session.commit()
        return run_id


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
        task_id = task.id
        finalization = _get_or_create_finalization(session, task)
        finalization_id = finalization.id

    validation_run_id: str | None = None
    validation_status: RunStatus | None = None

    if run_validation:
        validation_run_id = _prepare_validation_run(root, task_id, finalization_id)

        with session_factory() as session:
            run = session.get(EngineeringRun, validation_run_id)
            assert run is not None
            current_status = RunStatus(run.status)

        if current_status == RunStatus.RUNNING:
            validation_result = run_all_checks(root, resume_run_id=validation_run_id)
            validation_status = validation_result.status
        else:
            validation_status = current_status

        if validation_status != RunStatus.PASSED:
            with session_factory() as session:
                persisted_finalization = session.get(TaskFinalization, finalization_id)
                assert persisted_finalization is not None
                persisted_finalization.status = FinalizationStatus.FAILED
                session.commit()
            raise RuntimeError(
                f"Quality validation failed for task {task_id}. "
                "The task remains active; fix the failures and run `aeo task finish` again."
            )

    git_context = collect_git_context(root)
    completed_at = datetime.now(UTC)

    with session_factory() as session:
        task = session.get(EngineeringTask, task_id)
        persisted_finalization = session.get(TaskFinalization, finalization_id)

        assert task is not None
        assert persisted_finalization is not None

        started_at = _as_utc(task.started_at)
        task.status = TaskStatus.COMPLETED
        task.completed_at = completed_at
        task.duration_ms = (completed_at - started_at).total_seconds() * 1000
        task.end_branch = git_context.branch
        task.end_commit_sha = git_context.commit_sha
        task.changed_files = git_context.changed_files
        task.insertions = git_context.insertions
        task.deletions = git_context.deletions
        task.validation_run_id = validation_run_id

        persisted_finalization.validation_run_id = validation_run_id
        persisted_finalization.status = FinalizationStatus.COMPLETED
        persisted_finalization.completed_at = completed_at

        session.commit()
        return _to_summary(session, task)


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
        started_at = _as_utc(task.started_at)
        task.status = TaskStatus.CANCELLED
        task.completed_at = completed_at
        task.duration_ms = (completed_at - started_at).total_seconds() * 1000
        session.commit()
        return _to_summary(session, task)