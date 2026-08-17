from __future__ import annotations

import json
from pathlib import Path

from aeo.config import aeo_dir, project_config_path
from aeo.project.detection import detect_project


def initialize_project(root: Path) -> dict:
    detected = detect_project(root)

    config = {
        "version": 1,
        "project": {
            "name": root.name,
            "languages": detected.languages,
            "frameworks": detected.frameworks,
            "package_managers": detected.package_managers,
        },
        "checks": detected.checks,
        "autonomy": {
            "default_level": 2,
            "max_level": 3,
        },
    }

    aeo_dir(root).mkdir(parents=True, exist_ok=True)
    project_config_path(root).write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )
    return config


def load_project_config(root: Path) -> dict:
    path = project_config_path(root)
    if not path.exists():
        raise FileNotFoundError(
            "AEO is not initialized in this repository. Run `aeo init` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))
