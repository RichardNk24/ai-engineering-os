from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    stage: str | None
    message: str | None
    duration_ms: float | None
    created_at: datetime


class GitSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    branch: str | None
    commit_sha: str | None
    dirty_worktree: bool
    changed_files: int
    insertions: int
    deletions: int
    untracked_files: int


class EnvironmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aeo_version: str
    python_version: str
    implementation: str
    os_name: str
    os_release: str
    machine: str
    git_version: str | None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    command: str
    status: str
    project_root: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None
    events: list[EventRead]
    git_snapshot: GitSnapshotRead | None
    environment: EnvironmentRead | None


class TaskRead(BaseModel):
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
    validation_attempts: int
    validation_status: str | None
    validation_duration_ms: float | None
