"""AEO visual system. Renderables accept literal text; no model-controlled markup."""

import os
from contextlib import nullcontext

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from . import __version__
from .safety import display_safe, redact

THEME = Theme(
    {
        "brand": "bold #5eead4",
        "ink": "#e2e8f0",
        "muted": "#94a3b8",
        "line": "#334155",
        "good": "#86efac",
        "warn": "#fbbf24",
        "bad": "#fb7185",
    }
)
STATUS_STYLE = {
    "proposed": "brand",
    "validated": "good",
    "accepted": "good",
    "failed": "bad",
    "validation_failed": "bad",
    "interrupted": "warn",
    "dry_run": "muted",
    "discarded": "muted",
}


class UI:
    def __init__(self, *, json_mode=False, plain=False, console=None):
        self.json_mode = json_mode
        self.console = console or Console(
            theme=THEME, no_color=plain or "NO_COLOR" in os.environ, highlight=False
        )
        self.ascii = plain or os.environ.get("AEO_ASCII") == "1"

    def text(self, value, style="ink"):
        return Text(display_safe(redact(value)), style=style)

    def header(self, section="CONTROL ROOM"):
        if self.json_mode:
            return
        mark = "<>" if self.ascii else "◈"
        title = Text.assemble((f"{mark}  A E O", "brand"), ("   /   WORKBENCH", "ink"))
        meta = self.text(f"{__version__}  ·  {section}  ·  AI ENGINEERING OS", "muted")
        self.console.print()
        self.console.print(
            Panel(
                Group(title, meta),
                border_style="line",
                padding=(1, 2),
                box=box.ASCII if self.ascii else box.ROUNDED,
            )
        )

    def panel(self, title, body, style="line"):
        self.console.print(
            Panel(
                self.text(body),
                title=self.text(title, "brand"),
                title_align="left",
                border_style=style,
                padding=(1, 2),
                box=box.ASCII if self.ascii else box.ROUNDED,
            )
        )

    def emit(self, data):
        self.console.print_json(data=redact(data), indent=2)

    def busy(self, label):
        if self.json_mode or not self.console.is_terminal:
            return nullcontext()
        return self.console.status(self.text(label, "brand"), spinner="dots")

    def table(self, columns, rows):
        table = Table(box=box.SIMPLE, expand=True, header_style="muted", padding=(0, 1))
        for col in columns:
            table.add_column(col)
        for row in rows:
            table.add_row(*(cell if isinstance(cell, Text) else self.text(cell) for cell in row))
        self.console.print(table)

    def run(self, run):
        if self.json_mode:
            self.emit(run)
            return
        self.header("RUN / " + run["id"])
        status = run["status"]
        self.console.print(
            self.text("  " + status.upper().replace("_", " "), STATUS_STYLE.get(status, "ink"))
        )
        usage = run.get("usage") or {}
        cost = usage.get("estimated_cost_usd")
        cards = []
        for label, value in [
            ("BASE COMMIT", run["base"][:10]),
            ("CONTEXT", f"{run['context_bytes']:,} bytes"),
            ("TOKENS", str(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))),
            ("EST. COST", f"${cost:.5f}" if cost is not None else "unpriced"),
        ]:
            cards.append(
                Panel(
                    Group(self.text(label, "muted"), self.text(value, "brand")),
                    border_style="line",
                    box=box.ASCII if self.ascii else box.ROUNDED,
                )
            )
        count = 4 if self.console.width >= 96 else 2 if self.console.width >= 48 else 1
        grid = Table.grid(expand=True, padding=(0, 1))
        for _ in range(count):
            grid.add_column(ratio=1)
        for start in range(0, len(cards), count):
            grid.add_row(*cards[start : start + count])
        self.console.print(grid)
        stages = ["CONTEXT", "PROPOSE", "ISOLATE", "VALIDATE", "ACCEPT"]
        active = {
            "dry_run": 0,
            "planning": 0,
            "applying": 2,
            "proposed": 2,
            "validating": 3,
            "validated": 3,
            "accepted": 4,
        }.get(status, -1)
        flow = Text()
        for i, label in enumerate(stages):
            if i:
                flow.append("  /  ", "muted")
            flow.append(label, "brand" if i <= active else "muted")
        self.console.print(
            Panel(flow, border_style="line", box=box.ASCII if self.ascii else box.ROUNDED)
        )
        self.table(["WRITE SCOPE", "BOUNDARY"], [(p, "explicit") for p in run["writable_paths"]])
        if run.get("gates"):
            self.table(
                ["QUALITY GATE", "RESULT", "TIME"],
                [
                    (
                        g["name"],
                        self.text(
                            g["status"].upper(), "good" if g["status"] == "passed" else "bad"
                        ),
                        f"{g['duration_ms'] / 1000:.2f}s",
                    )
                    for g in run["gates"]
                ],
            )
        if run.get("error"):
            self.panel("DETAIL", run["error"], "bad")
        next_step = {
            "proposed": f"aeo workbench show {run['id']} --diff\naeo workbench pipeline {run['id']} --trust-code --allow-remote",
            "validated": f"aeo workbench accept {run['id']}",
            "accepted": "git diff --cached\nReview, then commit when ready.",
            "validation_failed": "Inspect local gate logs and the proposed code. No source changes applied.",
            "dry_run": "Context checked locally. No model call and no worktree created.",
        }.get(status, "aeo workbench runs")
        if status == "validated" and run.get("pipeline_required"):
            next_step = f"aeo workbench report {run['id']}"
        self.panel("NEXT ACTION", next_step)
        self.console.print(
            self.text("  HUMAN AUTHORITY  /  Local evidence. Explicit acceptance.\n", "muted")
        )

    def report(self, data):
        if self.json_mode:
            self.emit(data)
            return
        self.header("DECISION / " + data["run_id"])
        ready = data["ready_to_accept"]
        self.panel(
            "READY FOR YOUR DECISION" if ready else "ACCEPTANCE BLOCKED",
            "Evidence is current. Acceptance still requires your command."
            if ready
            else "\n".join(data["blocking_reasons"]),
            "good" if ready else "warn",
        )
        proof = data.get("pipeline") or {}
        if proof.get("fixture"):
            self.panel("OFFLINE FIXTURE", "Simulated Guardian/reviewer. No AI call. Cannot accept.")
        rows = [
            ("TEST / " + g["name"], g["status"], f"{g['duration_ms'] / 1000:.2f}s")
            for g in data["gates"]
        ]
        for stage in proof.get("stages", []):
            if stage["name"] != "gates":
                rows.append(
                    (
                        stage["name"].upper(),
                        stage["status"],
                        f"{stage.get('duration_ms', 0) / 1000:.2f}s",
                    )
                )
        self.table(["EVIDENCE", "RESULT", "TIME"], rows)
        self.table(
            ["IDENTITY", "VALUE"],
            [
                ("BASE", data["base"][:12]),
                ("PATCH SHA256", data.get("patch_sha256") or "pending"),
                ("ATTEMPT", proof.get("attempt", "none")),
            ],
        )
        for stage in proof.get("stages", []):
            if stage.get("summary"):
                self.panel(stage["name"].upper() + " / SUMMARY", stage["summary"])
            if stage.get("findings"):
                self.table(
                    ["SEVERITY", "LOCATION", "FINDING"],
                    [
                        (
                            f.get("severity", ""),
                            f.get("file_path") or "-",
                            f.get("title") or f.get("message", ""),
                        )
                        for f in stage["findings"]
                    ],
                )
            if stage.get("uncertainties"):
                self.panel("UNCERTAINTIES", "\n".join(stage["uncertainties"]), "warn")
            if stage.get("test_recommendations"):
                self.panel("RECOMMENDED TESTS", "\n".join(stage["test_recommendations"]))
        usage_rows = []
        usages = [("IMPLEMENTER", data.get("implementation_usage") or {})]
        usages.extend(("REVIEWER", s) for s in proof.get("stages", []) if s["name"] == "reviewer")
        for label, usage in usages:
            cost = usage.get("estimated_cost_usd")
            usage_rows.append(
                (
                    label,
                    str(usage.get("input_tokens", 0)),
                    str(usage.get("output_tokens", 0)),
                    f"${cost:.5f}" if cost is not None else "unpriced",
                )
            )
        self.table(["MODEL STAGE", "INPUT", "OUTPUT", "EST. USD"], usage_rows)
        if data.get("last_error"):
            self.panel("LAST FAILURE", data["last_error"], "bad")
        command = (
            f"aeo workbench accept {data['run_id']} --yes"
            if ready
            else f"aeo workbench show {data['run_id']} --diff"
        )
        self.panel("NEXT ACTION", command)
        self.console.print(self.text("  Local evidence: " + data["evidence_directory"], "muted"))

    def dashboard(self, rows):
        if self.json_mode:
            self.emit({"runs": rows})
            return
        self.header()
        self.panel(
            "BUILD WITH INTENT",
            "A request becomes a proposal.\nA proposal earns evidence. You decide what ships.",
        )
        self.table(
            ["RUN", "STATE", "MODEL", "CREATED"],
            [
                (
                    r["id"],
                    self.text(r["status"], STATUS_STYLE.get(r["status"], "ink")),
                    r.get("model") or "offline",
                    r["created_at"][:19],
                )
                for r in rows
            ],
        )
        if not rows:
            self.panel(
                "YOUR FIRST RUN",
                'aeo workbench demo\naeo workbench feature "Your task" --write src/example.py --dry-run',
            )
        self.console.print(
            self.text(
                "  feature  /  show  /  pipeline  /  report  /  accept  /  runs  /  doctor\n",
                "muted",
            )
        )
