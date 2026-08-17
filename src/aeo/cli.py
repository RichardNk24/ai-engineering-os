from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aeo import __version__
from aeo.analytics.service import engineering_analytics
from aeo.checks.runner import CheckResult, run_all_checks
from aeo.environment.service import collect_environment
from aeo.git.service import collect_git_context
from aeo.project.configuration import initialize_project, load_project_config
from aeo.tasks.service import (
    cancel_task,
    finish_task,
    get_active_task,
    get_task,
    get_task_validation_events,
    list_tasks,
    start_task,
)

app = typer.Typer(
    name="aeo",
    help="AI Engineering OS — measurable, risk-aware engineering automation.",
)
task_app = typer.Typer(help="Track engineering tasks and development cycles.")
app.add_typer(task_app, name="task")
console = Console()


def current_root() -> Path:
    return Path.cwd().resolve()


def _seconds(value_ms: float | None) -> str:
    return f"{(value_ms or 0) / 1000:.2f}s"


@app.command()
def version() -> None:
    """Show the installed AEO version."""
    console.print(f"AEO {__version__}")


@app.command()
def init() -> None:
    """Initialize AEO in the current repository."""
    root = current_root()
    config = initialize_project(root)
    console.print("[bold green]AEO initialized[/bold green]")
    console.print(f"Project: {config['project']['name']}")
    console.print(f"Languages: {', '.join(config['project']['languages']) or 'unknown'}")
    console.print(f"Frameworks: {', '.join(config['project']['frameworks']) or 'unknown'}")
    console.print(f"Checks: {', '.join(config['checks']) or 'none detected'}")


@app.command()
def doctor() -> None:
    """Inspect project, Git, and execution environment."""
    root = current_root()
    config = load_project_config(root)
    git_context = collect_git_context(root)
    environment = collect_environment(root)

    console.print_json(data=config)
    console.print()

    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"AEO: {environment.aeo_version}",
                    f"Python: {environment.python_version} ({environment.implementation})",
                    f"OS: {environment.os_name} {environment.os_release}",
                    f"Machine: {environment.machine or 'unknown'}",
                    f"Git: {environment.git_version or 'unavailable'}",
                ]
            ),
            title="Environment",
        )
    )

    if git_context.is_repository:
        console.print(
            Panel.fit(
                "\n".join(
                    [
                        f"Branch: {git_context.branch or 'detached'}",
                        f"Commit: {(git_context.commit_sha or 'unknown')[:12]}",
                        f"Dirty: {'yes' if git_context.dirty_worktree else 'no'}",
                        f"Changed files: {git_context.changed_files}",
                        f"Untracked files: {git_context.untracked_files}",
                    ]
                ),
                title="Git",
            )
        )
    else:
        console.print("[yellow]Git repository not detected.[/yellow]")


def _render_check_details(result: CheckResult) -> None:
    if result.passed:
        return
    console.print()
    console.print(
        Panel(
            (result.output or "Command failed without output.")[-6000:],
            title=f"[red]✗ {result.name.upper()}[/red] — {result.command}",
            border_style="red",
        )
    )


@app.command()
def check() -> None:
    """Run deterministic quality gates and record telemetry."""
    quality_run = run_all_checks(current_root())
    results = quality_run.checks

    if not results:
        console.print("[yellow]No checks configured.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title=f"AEO Quality Gates — {quality_run.run_id[:8]}")
    table.add_column("Check")
    table.add_column("Command")
    table.add_column("Status")
    table.add_column("Duration")

    for result in results:
        table.add_row(
            result.name,
            result.command,
            "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]",
            _seconds(result.duration_ms),
        )
    console.print(table)

    for result in results:
        _render_check_details(result)

    passed = all(result.passed for result in results)
    result_message = (
        "\n[bold green]RESULT: PASSED[/bold green]"
        if passed
        else "\n[bold red]RESULT: FAILED[/bold red]"
    )
    console.print(result_message)
    raise typer.Exit(code=0 if passed else 1)


@app.command()
def stats() -> None:
    """Show engineering outcome, task, and quality-gate analytics."""
    metrics = engineering_analytics(current_root())
    runs = metrics["runs"]
    tasks = metrics["tasks"]
    gates = metrics["gates"]
    assert isinstance(runs, dict)
    assert isinstance(tasks, dict)
    assert isinstance(gates, dict)

    summary = Table(title="AEO Engineering Analytics")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Runs", str(runs["total"]))
    summary.add_row("Run success", f'{runs["success_rate"]:.2f}%')
    summary.add_row("Median run duration", _seconds(float(runs["median_duration_ms"])))
    summary.add_row("P95 run duration", _seconds(float(runs["p95_duration_ms"])))
    summary.add_row("Tasks", str(tasks["total"]))
    summary.add_row("Completed tasks", str(tasks["completed"]))
    summary.add_row("First-pass success", f'{tasks["first_pass_success_rate"]:.2f}%')
    summary.add_row("Retry rate", f'{tasks["retry_rate"]:.2f}%')
    summary.add_row("Avg validation attempts", str(tasks["average_validation_attempts"]))
    summary.add_row("Median task duration", _seconds(float(tasks["median_duration_ms"])))
    summary.add_row("P95 task duration", _seconds(float(tasks["p95_duration_ms"])))
    console.print(summary)

    if gates:
        gate_table = Table(title="Quality Gate Analytics")
        gate_table.add_column("Gate")
        gate_table.add_column("Pass", justify="right")
        gate_table.add_column("Fail", justify="right")
        gate_table.add_column("Avg duration", justify="right")
        for name, values in sorted(gates.items()):
            assert isinstance(values, dict)
            gate_table.add_row(
                str(name),
                str(values["passed"]),
                str(values["failed"]),
                _seconds(float(values["average_duration_ms"])),
            )
        console.print(gate_table)


@task_app.command("start")
def task_start(title: str) -> None:
    """Start tracking an engineering task."""
    try:
        task = start_task(current_root(), title)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print("[bold green]Engineering task started[/bold green]")
    console.print(f"Task: {task.id}")
    console.print(f"Title: {task.title}")
    console.print(f"Branch: {task.start_branch or 'n/a'}")
    console.print(f"Base commit: {(task.start_commit_sha or 'n/a')[:12]}")


@task_app.command("status")
def task_status() -> None:
    """Show the active engineering task."""
    task = get_active_task(current_root())
    if task is None:
        console.print("[yellow]No active task.[/yellow]")
        return

    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"ID: {task.id}",
                    f"Title: {task.title}",
                    f"Status: {task.status}",
                    f"Branch: {task.start_branch or 'n/a'}",
                    f"Base commit: {(task.start_commit_sha or 'n/a')[:12]}",
                    f"Validation attempts: {task.validation_attempts}",
                ]
            ),
            title="Active Engineering Task",
        )
    )


@task_app.command("history")
def task_history(limit: int = typer.Option(20, min=1, max=200)) -> None:
    """Show recent engineering tasks."""
    tasks = list_tasks(current_root(), limit=limit)
    table = Table(title="AEO Task History")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Title")
    table.add_column("Duration")
    table.add_column("Attempts", justify="right")
    table.add_column("Validation")

    for task in tasks:
        table.add_row(
            task.id[:8],
            task.status,
            task.title,
            _seconds(task.duration_ms) if task.duration_ms is not None else "—",
            str(task.validation_attempts),
            task.validation_status or "—",
        )
    console.print(table)


@task_app.command("show")
def task_show(task_id: str) -> None:
    """Show one engineering task with validation history."""
    try:
        task = get_task(current_root(), task_id)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if task is None:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"ID: {task.id}",
                    f"Title: {task.title}",
                    f"Status: {task.status}",
                    f"Duration: {_seconds(task.duration_ms)}",
                    f"Branch: {task.start_branch or 'n/a'} → {task.end_branch or 'n/a'}",
                    (
                        "Commit: "
                        f"{(task.start_commit_sha or 'n/a')[:12]} → "
                        f"{(task.end_commit_sha or 'n/a')[:12]}"
                    ),
                    f"Changed files: {task.changed_files}",
                    f"Insertions: {task.insertions}",
                    f"Deletions: {task.deletions}",
                    f"Validation attempts: {task.validation_attempts}",
                    f"Final validation: {task.validation_status or 'not run'}",
                    f"Validation duration: {_seconds(task.validation_duration_ms)}",
                ]
            ),
            title="Engineering Task",
        )
    )

    events = get_task_validation_events(current_root(), task.id)
    gate_events = [
        event for event in events if event.stage and event.event_type.startswith("check_")
    ]
    if gate_events:
        table = Table(title="Validation Events")
        table.add_column("Gate")
        table.add_column("Event")
        table.add_column("Duration")
        for event in gate_events:
            table.add_row(event.stage or "—", event.event_type, _seconds(event.duration_ms))
        console.print(table)


@task_app.command("finish")
def task_finish(no_check: bool = typer.Option(False, "--no-check")) -> None:
    """Finish the active task; failed validation leaves it active for retry."""
    try:
        task = finish_task(current_root(), run_validation=not no_check)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print("[bold green]Engineering task completed[/bold green]")
    console.print(f"Task: {task.id}")
    console.print(f"Title: {task.title}")
    console.print(f"Duration: {_seconds(task.duration_ms)}")
    console.print(f"Changed files: {task.changed_files}")
    console.print(f"Insertions: {task.insertions}")
    console.print(f"Deletions: {task.deletions}")
    console.print(f"Validation attempts: {task.validation_attempts}")
    console.print(f"Validation: {task.validation_status or 'skipped'}")
    console.print(f"Validation run: {task.validation_run_id or 'skipped'}")


@task_app.command("cancel")
def task_cancel() -> None:
    """Cancel the active engineering task."""
    try:
        task = cancel_task(current_root())
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[yellow]Task cancelled:[/yellow] {task.id} — {task.title}")


if __name__ == "__main__":
    app()
