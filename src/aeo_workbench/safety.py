"""Local policy, not a substitute for an OS sandbox or a complete secret scanner."""

import hashlib
import re
from pathlib import Path, PurePosixPath


class WorkbenchError(RuntimeError):
    pass


BLOCKED_PARTS = {".git", ".aeo", ".aeo6", ".ssh", ".aws", ".venv", "node_modules"}
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bAKIA[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}|"
    r"\bsk-[A-Za-z0-9_-]{20,}|"
    r"""(?im:(?:api[_-]?key|secret|password|access[_-]?token)\s*[:=]\s*["'][^"'\n]{12,}["'])"""
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, name: str) -> Path:
    p = PurePosixPath(name)
    if (
        not name
        or name != p.as_posix()
        or p.is_absolute()
        or ".." in p.parts
        or "\\" in name
        or ":" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise WorkbenchError("Path must be a normalized relative POSIX path.")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if any(
        part.endswith((".", " "))
        or part.split(".")[0].lower() in reserved
        or any(c in part for c in '<>"|?*')
        for part in p.parts
    ):
        raise WorkbenchError("Path is not portable across Windows and POSIX systems.")
    if any(part.lower() in BLOCKED_PARTS for part in p.parts):
        raise WorkbenchError("Internal or credential directories are protected.")
    if any(part.startswith(".") for part in p.parts):
        raise WorkbenchError("Hidden files are excluded from V0.6 context and edits.")
    if p.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db"}:
        raise WorkbenchError("Credential and database files are excluded.")
    target = root.joinpath(*p.parts)
    for parent in [target, *target.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise WorkbenchError("Symlinks are not allowed in context or edits.")
    if not target.resolve().is_relative_to(root.resolve()):
        raise WorkbenchError("Path escapes repository.")
    return target


def inspect_text(value: str) -> None:
    if "\x00" in value:
        raise WorkbenchError("Binary content is not supported.")
    if SECRET.search(value):
        raise WorkbenchError("Potential credential detected; nothing sent to the provider.")


def display_safe(value: object) -> str:
    # Never allow repo/provider text to inject ANSI / OSC / terminal control sequences.
    return "".join(
        c for c in str(value) if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) <= 159)
    )


def redact(value):
    """Mask recognizable API keys in metadata, including historical V0.6 rows."""
    if isinstance(value, str):
        return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [redact(v) for v in value]
    return value
