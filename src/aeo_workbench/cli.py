import json
import os
from functools import wraps
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.syntax import Syntax

from . import __version__, engine, storage
from .gitops import head, repo_root
from .safety import WorkbenchError, display_safe
from .ui import UI

app = typer.Typer(
    no_args_is_help=False,
    help="AEO Workbench · isolated changes, measured evidence.",
    pretty_exceptions_enable=False,
)
ui = UI()


def root():
    return repo_root(Path.cwd())


def handled(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (WorkbenchError, ValidationError, OSError, ValueError) as exc:
            message = (
                str(exc)
                if isinstance(exc, WorkbenchError)
                else (
                    "Invalid configuration or unavailable file. Check doctor and the local config."
                )
            )
            if ui.json_mode:
                ui.emit({"error": message})
            else:
                ui.header("ACTION REQUIRED")
                ui.panel("CANNOT CONTINUE", message, "bad")
            raise typer.Exit(2) from None
        except KeyboardInterrupt:
            if ui.json_mode:
                ui.emit({"error": "Interrupted"})
            else:
                ui.panel(
                    "INTERRUPTED", "Operation stopped. Use runs / doctor to inspect state.", "warn"
                )
            raise typer.Exit(130) from None

    return wrapper


@app.callback(invoke_without_command=True)
@handled
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    plain: bool = typer.Option(False, "--plain"),
):
    """JSON and plain-output flags precede the command."""
    global ui
    ui = UI(json_mode=json_output, plain=plain)
    if ctx.invoked_subcommand is None:
        ui.dashboard(storage.history(root()))


@app.command()
def version():
    if ui.json_mode:
        ui.emit({"version": __version__})
    else:
        ui.header("VERSION")


@app.command()
@handled
def init():
    """Initialize additive Workbench state without touching V0.5 configuration."""
    path = storage.initialize(root())
    if ui.json_mode:
        ui.emit({"config": str(path), "version": __version__})
    else:
        ui.header("INITIALIZED")
        ui.panel("CONFIGURATION", f"{path}\n\nSet your model and quality gates here.")
        ui.panel("START HERE", "aeo6 demo\naeo6 doctor")


@app.command()
@handled
def doctor():
    """Inspect prerequisites and recovery state without model calls."""
    r = root()
    cfg = storage.config(r)
    info = {
        "root": str(r),
        "head": head(r),
        "model": cfg.model,
        "review_model": cfg.review_model or cfg.model,
        "require_pipeline": cfg.require_pipeline,
        "workbench_source": str(Path(__file__).resolve().parent),
        "api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "gates": [g.model_dump() for g in cfg.gates],
        "config": str(storage.state_dir(r) / "config.json"),
        "operation_locked": (storage.state_dir(r) / "operation.lock").exists(),
    }
    if ui.json_mode:
        ui.emit(info)
    else:
        ui.header("SYSTEM CHECK")
        ui.table(
            ["COMPONENT", "VALUE"],
            [(k, json.dumps(v) if isinstance(v, list) else str(v)) for k, v in info.items()],
        )


@app.command("bridge-check")
@handled
def bridge_check():
    """Check imports of the installed V0.5 services; no tests or model calls."""
    import tempfile

    from .pipeline import LegacyBridge

    r = root()
    with tempfile.TemporaryDirectory(prefix="probe-", dir=storage.state_dir(r)) as directory:
        result = LegacyBridge().call("probe", r, storage.config(r), Path(directory))
    if ui.json_mode:
        ui.emit(result)
    else:
        ui.header("CORE CONNECTION")
        ui.panel(
            "V0.5 SERVICES AVAILABLE", "Guardian and reviewer import successfully. No model called."
        )


@app.command()
@handled
def feature(
    task: str,
    read: list[str] = typer.Option([], "--read"),
    write: list[str] = typer.Option([], "--write"),
    model: str | None = typer.Option(None, "--model"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    allow_remote: bool = typer.Option(False, "--allow-remote"),
):
    """Propose a change in an isolated Git worktree; send only selected files."""
    if not dry_run and not allow_remote:
        raise WorkbenchError(
            "Use --dry-run locally, or --allow-remote to send the task and selected files."
        )
    with ui.busy("Building a reviewable change…"):
        run = engine.prepare(root(), task, read, write, model=model, dry_run=dry_run)
    ui.run(run)


@app.command()
@handled
def runs(limit: int = typer.Option(20, min=1, max=200)):
    """Show locally recorded runs."""
    ui.dashboard(storage.history(root(), limit))


@app.command()
@handled
def show(run_id: str, diff: bool = typer.Option(False, "--diff")):
    """Inspect the plan and optional literal diff before executing any generated code."""
    r = root()
    run = storage.get(r, run_id)
    rd = storage.run_dir(r, run_id)
    proposal = rd / "proposal.json"
    payload = json.loads(proposal.read_text(encoding="utf-8")) if proposal.exists() else None
    patch_path = rd / "change.patch"
    patch = patch_path.read_text(encoding="utf-8") if diff and patch_path.exists() else None
    if ui.json_mode:
        ui.emit({"run": run, "proposal": payload, "diff": patch})
        return
    ui.run(run)
    if payload:
        ui.panel(
            "IMPLEMENTATION PLAN",
            payload["summary"]
            + "\n\n"
            + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(payload["steps"])),
        )
        if payload["risks"]:
            ui.panel("REVIEW POINTS", "\n".join(payload["risks"]), "warn")
    if patch:
        ui.console.print(Syntax(display_safe(patch), "diff", theme="ansi_dark", word_wrap=True))


@app.command()
@handled
def validate(run_id: str, trust_code: bool = typer.Option(False, "--trust-code")):
    """Execute your configured gates after reviewing code; a worktree is not a sandbox."""
    with ui.busy("Collecting deterministic evidence…"):
        run = engine.validate(root(), run_id, trust_code=trust_code)
    ui.run(run)
    if run["status"] != "validated":
        raise typer.Exit(1)


@app.command()
@handled
def pipeline(
    run_id: str,
    trust_code: bool = typer.Option(False, "--trust-code"),
    allow_remote: bool = typer.Option(False, "--allow-remote"),
):
    """Run gates, Guardian and verified AI review of the staged proposal, in order."""
    from .pipeline import run_pipeline
    from .report import build_report

    with ui.busy("Tests > Guardian > Reviewer > decision brief…"):
        run_pipeline(root(), run_id, trust_code=trust_code, allow_remote=allow_remote)
    ui.report(build_report(root(), run_id))


@app.command()
@handled
def report(run_id: str, output: Path | None = typer.Option(None, "--output")):
    """Show acceptance readiness and evidence; optionally export JSON to a new file."""
    from .report import build_report

    data = build_report(root(), run_id)
    if output:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
    ui.report(data)


@app.command()
@handled
def accept(run_id: str, yes: bool = typer.Option(False, "--yes")):
    """Apply a validated patch to the clean source tree and index. No commit or push."""
    if not yes:
        if ui.json_mode or not ui.console.is_terminal:
            raise WorkbenchError("Acceptance requires --yes in non-interactive mode.")
        if not typer.confirm("Apply this validated patch to your source tree and stage it?"):
            raise typer.Exit(1)
    ui.run(engine.accept(root(), run_id))


@app.command()
@handled
def discard(run_id: str, yes: bool = typer.Option(False, "--yes")):
    """Delete this run's worktree; retain proposal, patch and audit history."""
    if not yes:
        if ui.json_mode or not ui.console.is_terminal:
            raise WorkbenchError("Discard requires --yes in non-interactive mode.")
        if not typer.confirm("Delete the isolated worktree, including any manual edits there?"):
            raise typer.Exit(1)
    ui.run(engine.discard(root(), run_id))


@app.command()
@handled
def demo(pipeline_demo: bool = typer.Option(False, "--pipeline")):
    """Run a real isolated Git + test workflow with an explicitly offline fixture."""
    from .demo import run_demo

    with ui.busy("Running the offline demonstration…"):
        r, run = run_demo(full_pipeline=pipeline_demo)
    if ui.json_mode:
        ui.emit({"demo": "offline-fixture", "repository": str(r), "run": run})
    else:
        if pipeline_demo:
            from .report import build_report

            ui.report(build_report(r, run["id"]))
        else:
            ui.run(run)
        ui.panel(
            "OFFLINE DEMO / REAL GIT + TESTS",
            f"No model called. Fixture changes only.\n\nRepository: {r}\n"
            f'cd "{r}"\naeo6 show {run["id"]} --diff',
        )


@app.command()
@handled
def serve(port: int = typer.Option(8766, min=1024, max=65535)):
    """Serve authenticated read-only telemetry on 127.0.0.1."""
    import uvicorn

    from .api import create_app

    token = os.environ.get("AEO_API_TOKEN", "")
    if len(token) < 24:
        raise WorkbenchError("Set AEO_API_TOKEN to a random token of at least 24 characters.")
    uvicorn.run(create_app(root(), token), host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
