from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DetectedProject:
    languages: list[str]
    frameworks: list[str]
    package_managers: list[str]
    checks: dict[str, str]


def detect_project(root: Path) -> DetectedProject:
    languages: list[str] = []
    frameworks: list[str] = []
    package_managers: list[str] = []
    checks: dict[str, str] = {}

    pyproject = root / "pyproject.toml"
    package_json = root / "package.json"

    if pyproject.exists():
        languages.append("python")

        text = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
        if "fastapi" in text:
            frameworks.append("fastapi")

        if (root / "uv.lock").exists():
            package_managers.append("uv")
        elif (root / "poetry.lock").exists():
            package_managers.append("poetry")
        else:
            package_managers.append("pip")

        if "ruff" in text:
            checks["lint"] = "ruff check ."
        if "mypy" in text:
            checks["types"] = "mypy ."
        if "pytest" in text:
            checks["test"] = "pytest"

    if package_json.exists():
        languages.append("typescript/javascript")
        text = package_json.read_text(encoding="utf-8", errors="ignore").lower()

        if "next" in text:
            frameworks.append("nextjs")
        if "@nestjs/core" in text:
            frameworks.append("nestjs")

        if (root / "pnpm-lock.yaml").exists():
            package_managers.append("pnpm")
            checks.setdefault("lint", "pnpm lint")
            checks.setdefault("test", "pnpm test")
            checks.setdefault("build", "pnpm build")
        elif (root / "yarn.lock").exists():
            package_managers.append("yarn")
        else:
            package_managers.append("npm")

    return DetectedProject(
        languages=languages,
        frameworks=frameworks,
        package_managers=package_managers,
        checks=checks,
    )
