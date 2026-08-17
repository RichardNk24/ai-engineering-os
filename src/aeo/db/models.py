from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aeo.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class EngineeringRun(Base):
    __tablename__ = "engineering_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    command: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    project_root: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    events: Mapped[list[EngineeringEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    git_snapshot: Mapped[GitSnapshot | None] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )


class EngineeringEvent(Base):
    __tablename__ = "engineering_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("engineering_runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[EngineeringRun] = relationship(back_populates="events")


class GitSnapshot(Base):
    __tablename__ = "git_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_runs.id"),
        unique=True,
        index=True,
    )
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dirty_worktree: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    insertions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    untracked_files: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[EngineeringRun] = relationship(back_populates="git_snapshot")


class EngineeringTask(Base):
    __tablename__ = "engineering_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    project_root: Mapped[str] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    start_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    end_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)

    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    insertions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)

    validation_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("engineering_runs.id"),
        nullable=True,
    )
