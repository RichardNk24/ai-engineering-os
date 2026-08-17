from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GitContext:
    is_repository: bool
    branch: str | None
    commit_sha: str | None
    dirty_worktree: bool
    changed_files: int
    insertions: int
    deletions: int
    untracked_files: int


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repository(root: Path) -> bool:
    result = _run_git(root, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def collect_git_context(root: Path) -> GitContext:
    if not is_git_repository(root):
        return GitContext(
            is_repository=False,
            branch=None,
            commit_sha=None,
            dirty_worktree=False,
            changed_files=0,
            insertions=0,
            deletions=0,
            untracked_files=0,
        )

    branch_result = _run_git(root, "branch", "--show-current")
    sha_result = _run_git(root, "rev-parse", "HEAD")
    status_result = _run_git(root, "status", "--porcelain")
    diff_result = _run_git(root, "diff", "--shortstat", "HEAD")

    status_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    untracked = sum(1 for line in status_lines if line.startswith("??"))

    changed_files = 0
    insertions = 0
    deletions = 0

    if diff_result.returncode == 0 and diff_result.stdout.strip():
        text = diff_result.stdout.strip()

        files_match = re.search(r"(\d+)\s+files?\s+changed", text)
        insertions_match = re.search(r"(\d+)\s+insertions?\(\+\)", text)
        deletions_match = re.search(r"(\d+)\s+deletions?\(-\)", text)

        changed_files = int(files_match.group(1)) if files_match else 0
        insertions = int(insertions_match.group(1)) if insertions_match else 0
        deletions = int(deletions_match.group(1)) if deletions_match else 0

    # Untracked files are not included by `git diff HEAD`.
    tracked_changes = sum(1 for line in status_lines if not line.startswith("??"))
    changed_files = max(changed_files, tracked_changes) + untracked

    return GitContext(
        is_repository=True,
        branch=branch_result.stdout.strip() or None,
        commit_sha=sha_result.stdout.strip() or None,
        dirty_worktree=bool(status_lines),
        changed_files=changed_files,
        insertions=insertions,
        deletions=deletions,
        untracked_files=untracked,
    )
