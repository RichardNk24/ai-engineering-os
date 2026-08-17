from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ChangedLine:
    file_path: str
    line_number: int
    content: str


@dataclass(slots=True)
class DiffSnapshot:
    files: list[str]
    changed_lines: list[ChangedLine]
    untracked_files: list[str]


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_unified_zero(diff_text: str) -> tuple[list[str], list[ChangedLine]]:
    files: list[str] = []
    lines: list[ChangedLine] = []
    current_file: str | None = None
    new_line = 0

    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            if current_file not in files:
                files.append(current_file)
            continue
        if raw.startswith("@@"):
            match = _HUNK.match(raw)
            if match is not None:
                new_line = int(match.group(1))
            continue
        if current_file is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lines.append(ChangedLine(current_file, new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        elif raw.startswith(" "):
            new_line += 1

    return files, lines


def collect_diff(
    root: Path,
    *,
    staged: bool = False,
    max_file_bytes: int = 1_000_000,
) -> DiffSnapshot:
    diff_args = ["diff", "--unified=0", "--no-color"]
    names_args = ["diff", "--name-only", "--no-color"]
    if staged:
        diff_args.append("--cached")
        names_args.append("--cached")
    else:
        diff_args.append("HEAD")
        names_args.append("HEAD")

    result = _git(root, *diff_args)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "Unable to read Git diff.")

    parsed_files, lines = _parse_unified_zero(result.stdout)
    names_result = _git(root, *names_args)
    tracked_files = [
        line.strip()
        for line in names_result.stdout.splitlines()
        if line.strip()
    ]
    files = list(dict.fromkeys([*tracked_files, *parsed_files]))

    untracked: list[str] = []
    if not staged:
        untracked_result = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
        untracked = [item for item in untracked_result.stdout.split("\0") if item]
        for relative in untracked:
            path = root / relative
            if path.is_dir():
                continue
            if relative not in files:
                files.append(relative)
            try:
                if path.stat().st_size > max_file_bytes:
                    continue
                data = path.read_bytes()
                if b"\x00" in data:
                    continue
                text = data.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, content in enumerate(text.splitlines(), start=1):
                lines.append(ChangedLine(relative, number, content))

    return DiffSnapshot(
        files=files,
        changed_lines=lines,
        untracked_files=untracked,
    )
