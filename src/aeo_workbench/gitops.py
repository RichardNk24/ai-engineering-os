import os
import subprocess
from pathlib import Path

from .safety import WorkbenchError


def git(root: Path, *args: str, binary: bool = False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    try:
        p = subprocess.run(
            ["git", "-c", "core.hooksPath=", "-c", "core.fsmonitor=false", *args],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkbenchError("Git unavailable or timed out.") from exc
    if p.returncode:
        raise WorkbenchError(f"Git {args[0]} failed. Check repository state and permissions.")
    return p.stdout if binary else p.stdout.decode("utf-8", "strict").strip()


def repo_root(path: Path) -> Path:
    return Path(git(path.resolve(), "rev-parse", "--show-toplevel")).resolve()


def head(root: Path) -> str:
    return git(root, "rev-parse", "--verify", "HEAD")


def clean(root: Path) -> None:
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise WorkbenchError(
            "Commit or stash repository changes first (including untracked files)."
        )


def tracked_files(root: Path) -> set[str]:
    return set(git(root, "ls-files", "-z", binary=True).decode().rstrip("\0").split("\0"))
