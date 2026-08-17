from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from aeo.config import database_path
from aeo.db.base import Base
from aeo.db.models import (
    AeoSchemaMetadata,
    EngineeringTask,
    TaskFinalization,
    TaskValidationAttempt,
)
from aeo.domain.enums import FinalizationStatus, TaskStatus

CURRENT_SCHEMA_VERSION = 3


def _ensure_schema_version(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        metadata = session.get(AeoSchemaMetadata, 1)
        if metadata is None:
            session.add(AeoSchemaMetadata(id=1, schema_version=CURRENT_SCHEMA_VERSION))
            session.commit()
            return

        if metadata.schema_version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                "This AEO database was created by a newer schema version "
                f"({metadata.schema_version}); installed AEO supports "
                f"schema {CURRENT_SCHEMA_VERSION}. Upgrade AEO before continuing."
            )

        if metadata.schema_version < CURRENT_SCHEMA_VERSION:
            metadata.schema_version = CURRENT_SCHEMA_VERSION
            session.commit()


def _backfill_v03_compatibility(factory: sessionmaker[Session]) -> None:
    """Backfill V0.2 task validation links into V0.3 additive tables."""
    with factory() as session:
        legacy_tasks = session.scalars(
            select(EngineeringTask).where(EngineeringTask.validation_run_id.is_not(None))
        ).all()

        changed = False
        for task in legacy_tasks:
            assert task.validation_run_id is not None

            finalization = session.scalar(
                select(TaskFinalization).where(TaskFinalization.task_id == task.id)
            )
            if finalization is None:
                finalization = TaskFinalization(
                    task_id=task.id,
                    status=(
                        FinalizationStatus.COMPLETED
                        if task.status == TaskStatus.COMPLETED
                        else FinalizationStatus.VALIDATED
                    ),
                    validation_run_id=task.validation_run_id,
                    attempts=1,
                    started_at=task.completed_at or task.started_at,
                    completed_at=task.completed_at,
                )
                session.add(finalization)
                changed = True

            attempt = session.scalar(
                select(TaskValidationAttempt).where(
                    TaskValidationAttempt.run_id == task.validation_run_id
                )
            )
            if attempt is None:
                session.add(
                    TaskValidationAttempt(
                        task_id=task.id,
                        run_id=task.validation_run_id,
                        attempt_number=1,
                    )
                )
                changed = True

        if changed:
            session.commit()


def create_session_factory(project_root: Path) -> sessionmaker[Session]:
    db_path = database_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    _backfill_v03_compatibility(factory)
    _ensure_schema_version(factory)
    return factory
