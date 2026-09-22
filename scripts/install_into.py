"""Consolidate Workbench into an existing AEO core, preserving core metadata.

Run with the core project's virtualenv Python. Never run against the ZIP
extraction directory as --project. Backups are outside the repository.
"""

import argparse
import ast
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tomllib
import uuid
from datetime import datetime
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]


def replace_table(text, name, transform):
    pattern = rf"(?ms)^(\[{re.escape(name)}\][^\S\n]*\n)(.*?)(?=^\[|\Z)"
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"Missing supported TOML section: {name}")
    return text[: match.start()] + match[1] + transform(match[2]) + text[match.end() :]


def upgrade_metadata(text):
    data = tomllib.loads(text)
    if data.get("project", {}).get("name") != "ai-engineering-os":
        raise ValueError(
            "Expected the original ai-engineering-os project, not the extension package."
        )
    if data.get("build-system", {}).get("build-backend") != "hatchling.build":
        raise ValueError("This installer supports the current Hatchling core configuration only.")
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    if "src/aeo" not in packages:
        raise ValueError("Core package src/aeo must be preserved.")
    packages = list(dict.fromkeys([*packages, "src/aeo_workbench"]))

    def wheel(body):
        pattern = r"(?ms)^packages\s*=\s*\[.*?\]"
        if len(re.findall(pattern, body)) != 1:
            raise ValueError("Unsupported wheel packages declaration.")
        return re.sub(pattern, "packages = " + json.dumps(packages), body)

    text = replace_table(text, "tool.hatch.build.targets.wheel", wheel)
    existing = data["project"].get("scripts", {})

    def scripts(body):
        for command in ["aeo6", "aeo7"]:
            expected = "aeo_workbench.cli:app"
            if command in existing and existing[command] != expected:
                raise ValueError(f"Existing command {command} has another owner.")
            if command not in existing:
                body = body.rstrip() + f'\n{command} = "{expected}"\n\n'
        return body

    text = replace_table(text, "project.scripts", scripts)
    parsed = tomllib.loads(text)
    assert parsed["project"]["name"] == data["project"]["name"]
    assert parsed["project"]["version"] == data["project"]["version"]
    assert parsed["project"]["dependencies"] == data["project"]["dependencies"]
    return text


def upgrade_cli(text):
    tree = ast.parse(text)
    mounted = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_typer"
        and any(
            k.arg == "name" and isinstance(k.value, ast.Constant) and k.value.value == "workbench"
            for k in node.keywords
        )
        for node in ast.walk(tree)
    )
    if mounted:
        return text
    lines = text.splitlines(keepends=True)
    import_line = max(
        (node.end_lineno for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))),
        default=0,
    )
    lines.insert(import_line, "from aeo_workbench.cli import app as workbench_app\n")
    text = "".join(lines)
    addition = '\napp.add_typer(workbench_app, name="workbench")\n\n'
    match = re.search(r"^if __name__\s*==", text, flags=re.M)
    result = text[: match.start()] + addition + text[match.start() :] if match else text + addition
    ast.parse(result)
    return result


def install(project: Path, *, check_only=False):
    project = project.resolve()
    expected_python = (
        project / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )
    if Path(sys.prefix).resolve() != (project / ".venv").resolve():
        raise ValueError(f"Use the core virtualenv Python: {expected_python}")
    git_root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=project, text=True
        ).strip()
    ).resolve()
    if git_root != project:
        raise ValueError("--project must be the repository root.")
    metadata = project / "pyproject.toml"
    cli = project / "src/aeo/cli.py"
    if not cli.is_file() or not (project / "src/aeo/reviewer/service.py").is_file():
        raise ValueError("The restored V0.5 core and reviewer are required before this upgrade.")
    changes = {
        "pyproject.toml": upgrade_metadata(metadata.read_text(encoding="utf-8-sig")).encode(),
        "src/aeo/cli.py": upgrade_cli(cli.read_text(encoding="utf-8-sig")).encode(),
    }
    for directory in ["src/aeo_workbench", "tests"]:
        for source in sorted((BUNDLE / directory).glob("*.py")):
            changes[f"{directory}/{source.name}"] = source.read_bytes()
    changes["docs/WORKBENCH_V07.md"] = (BUNDLE / "README.md").read_bytes()
    for name in changes:
        target = project / name
        if target.is_symlink() or not target.resolve().is_relative_to(project):
            raise ValueError(f"Refusing an unsafe destination: {name}")
    print(f"Core: {project}\nWorkbench: 0.7.0\nFiles: {len(changes)}")
    if check_only:
        print("Preflight passed. No files or packages changed.")
        return
    backup = (
        project.parent
        / "aeo-upgrade-backups"
        / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    )
    backup.mkdir(parents=True)
    receipt = {"project": str(project), "files": {}, "bundle": str(BUNDLE)}
    try:
        previous = importlib.metadata.distribution("aeo-workbench")
        receipt["previous_workbench_version"] = previous.version
        direct = json.loads(previous.read_text("direct_url.json") or "{}")
        if direct.get("url", "").startswith("file:"):
            receipt["previous_local_install"] = direct
    except importlib.metadata.PackageNotFoundError:
        pass
    for name in changes:
        target = project / name
        receipt["files"][name] = target.exists()
        if target.exists():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    (backup / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"BACKUP: {backup}", flush=True)
    for name, content in changes.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    # Drop the obsolete separately-installed namespace. Core now packages both namespaces.
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "aeo-workbench"], check=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[ai,dev]"], cwd=project, check=True
    )
    verification = (
        "from pathlib import Path; import aeo_workbench; "
        "assert aeo_workbench.__version__ == '0.7.0'; "
        "assert Path(aeo_workbench.__file__).resolve() == "
        "Path('src/aeo_workbench/__init__.py').resolve(); "
        "from aeo.guardian.service import run_guard; "
        "from aeo.reviewer.service import run_review; print('Workbench source and core imports OK')"
    )
    subprocess.run([sys.executable, "-c", verification], cwd=project, check=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=project, check=True)
    print("Upgrade verified. Review git diff before committing. Core version is preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        install(args.project, check_only=args.check_only)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(
            f"Upgrade stopped: {exc}\nAny completed backup remains at the printed BACKUP path.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
