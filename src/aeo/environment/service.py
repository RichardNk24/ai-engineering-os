from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from aeo import __version__


@dataclass(slots=True, frozen=True)
class EnvironmentSnapshot:
    aeo_version: str
    python_version: str
    implementation: str
    os_name: str
    os_release: str
    machine: str
    git_version: str | None


def _git_version(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "--version"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def collect_environment(root: Path) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        aeo_version=__version__,
        python_version=platform.python_version(),
        implementation=platform.python_implementation(),
        os_name=platform.system() or sys.platform,
        os_release=platform.release(),
        machine=platform.machine(),
        git_version=_git_version(root),
    )
