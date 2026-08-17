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
