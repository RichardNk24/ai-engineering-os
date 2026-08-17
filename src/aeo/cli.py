from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aeo.checks.runner import CheckResult, run_all_checks
from aeo.git.service import collect_git_context
from aeo.project.configuration import initialize_project, load_project_config
from aeo.tasks.service import cancel_task, finish_task, get_active_task, start_task
from aeo.telemetry.service import stats as collect_stats

app = typer.Typer(
    name="aeo",
    help="AI Engineering OS — measurable, risk-aware engineering automation.",
)
task_app = typer.Typer(help="Track engineering tasks and development cycles.")
app.add_typer(task_app, name="task")

console = Console()


def current_root() -> Path:
    return Path.cwd().resolve()


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
    """Inspect the current AEO project configuration and Git environment."""
    config = load_project_config(current_root())
    git_context = collect_git_context(current_root())

    console.print_json(data=config)
    console.print()

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

    output = result.output or "Command failed without output."
    console.print()
    console.print(
        Panel(
            output[-6000:],
            title=f"[red]✗ {result.name.upper()}[/red] — {result.command}",
            border_style="red",
        )
    )


@app.command()
def check() -> None:
    """Run deterministic project quality gates and record telemetry."""
    results = run_all_checks(current_root())

    if not results:
        console.print("[yellow]No checks configured.[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="AEO Quality Gates")
    table.add_column("Check")
    table.add_column("Command")
    table.add_column("Status")
    table.add_column("Duration")

    failed = False
    for result in results:
        failed = failed or not result.passed
        table.add_row(
            result.name,
            result.command,
            "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]",
            f"{result.duration_ms / 1000:.2f}s",
        )

    console.print(table)

    for result in results:
        _render_check_details(result)

    if failed:
        console.print("\n[bold red]RESULT: FAILED[/bold red]")
    else:
        console.print("\n[bold green]RESULT: PASSED[/bold green]")

    raise typer.Exit(code=1 if failed else 0)


@app.command()
def stats() -> None:
    """Show basic engineering-run metrics."""
    metrics = collect_stats(current_root())

    table = Table(title="AEO Engineering Metrics")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Runs", str(metrics["runs"]))
    table.add_row("Passed", str(metrics["passed"]))
    table.add_row("Failed", str(metrics["failed"]))
    table.add_row("Success rate", f'{metrics["success_rate"]:.2f}%')
    table.add_row("Average duration", f'{metrics["average_duration_ms"] / 1000:.2f}s')

    console.print(table)


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
                ]
            ),
            title="Active Engineering Task",
        )
    )


@task_app.command("finish")
def task_finish(no_check: bool = typer.Option(False, "--no-check")) -> None:
    """Finish the active engineering task and optionally validate it."""
    try:
        task = finish_task(current_root(), run_validation=not no_check)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print("[bold green]Engineering task completed[/bold green]")
    console.print(f"Task: {task.id}")
    console.print(f"Title: {task.title}")
    console.print(f"Duration: {(task.duration_ms or 0) / 1000:.2f}s")
    console.print(f"Changed files: {task.changed_files}")
    console.print(f"Insertions: {task.insertions}")
    console.print(f"Deletions: {task.deletions}")
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
