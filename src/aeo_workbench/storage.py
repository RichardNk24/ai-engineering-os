import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .gitops import git
from .models import Settings
from .safety import WorkbenchError, redact


def now() -> str:
    return datetime.now(UTC).isoformat()


def state_dir(root: Path) -> Path:
    # Outside the working tree; V0.5 .aeo and its SQLite schema are untouched.
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = root / common
    path = common.resolve() / "aeo-workbench"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def config(root: Path) -> Settings:
    p = state_dir(root) / "config.json"
    if not p.exists():
        raise WorkbenchError("Run aeo6 init first.")
    return Settings.model_validate_json(p.read_text(encoding="utf-8"))


def initialize(root: Path) -> Path:
    p = state_dir(root) / "config.json"
    if not p.exists():
        p.write_text(Settings().model_dump_json(indent=2), encoding="utf-8")
    return p


def run_dir(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise WorkbenchError("Expected a complete 12-character run ID.")
    p = state_dir(root) / "runs" / run_id
    if not p.exists():
        raise WorkbenchError("Run not found.")
    return p


@contextmanager
def connection(root: Path):
    db = sqlite3.connect(state_dir(root) / "telemetry.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id TEXT NOT NULL, at TEXT NOT NULL, state TEXT NOT NULL)"
    )
    try:
        with db:
            yield db
    finally:
        db.close()


def save(root: Path, run: dict) -> None:
    run["updated_at"] = now()
    with connection(root) as db:
        db.execute(
            "INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (run["id"], json.dumps(redact(run))),
        )
        db.execute(
            "INSERT INTO events(run_id,at,state) VALUES (?,?,?)",
            (run["id"], run["updated_at"], run["status"]),
        )


def get(root: Path, run_id: str) -> dict:
    run_dir(root, run_id)
    with connection(root) as db:
        row = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise WorkbenchError("Run not found.")
    return redact(json.loads(row["data"]))


def history(root: Path, limit: int = 20) -> list[dict]:
    with connection(root) as db:
        rows = db.execute("SELECT data FROM runs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    return [redact(json.loads(row["data"])) for row in rows]


def events(root: Path, run_id: str) -> list[dict]:
    get(root, run_id)
    with connection(root) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT seq,at,state FROM events WHERE run_id=? ORDER BY seq", (run_id,)
            )
        ]


@contextmanager
def lock(root: Path):
    """Cross-platform exclusive lock. Stale locks require explicit human recovery."""
    p = state_dir(root) / "operation.lock"
    try:
        f = p.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise WorkbenchError(
            "Another operation holds the lock; see doctor / recovery guide."
        ) from exc
    try:
        import os

        with f:
            f.write(str(os.getpid()))
        yield
    finally:
        p.unlink(missing_ok=True)
