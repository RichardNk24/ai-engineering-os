from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from aeo.domain.enums import GuardCategory, GuardSeverity
from aeo.git.diff import DiffSnapshot


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: GuardSeverity
    category: GuardCategory
    message: str
    file_path: str | None = None
    line_number: int | None = None
    autofixable: bool = False

    @property
    def fingerprint(self) -> str:
        payload = "|".join(
            [
                self.rule_id,
                self.file_path or "",
                str(self.line_number or 0),
                self.message,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PY_DEBUG = re.compile(r"\b(?:breakpoint\(\)|pdb\.set_trace\(\))")
_JS_DEBUG = re.compile(r"(?:^|\s)debugger\s*;")
_CONFLICT = re.compile(r"^(?:<{7}|={7}|>{7})")
_CACHE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"}
_SOURCE_SUFFIXES = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx"}
_TEST_MARKERS = {"test", "tests", "spec", "specs"}


def _suffix(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def analyze_diff(snapshot: DiffSnapshot) -> list[Finding]:
    findings: list[Finding] = []

    for path in snapshot.files:
        normalized = path.replace("\\", "/")
        path_parts = set(normalized.split("/"))
        filename = normalized.rsplit("/", 1)[-1]
        if (filename == ".env" or filename.startswith(".env.")) and filename != ".env.example":
            findings.append(
                Finding(
                    rule_id="security.env-file",
                    severity=GuardSeverity.BLOCKER,
                    category=GuardCategory.SECURITY,
                    message="Environment/secrets file is part of the change set.",
                    file_path=path,
                )
            )
        if path_parts & _CACHE_PARTS or filename.endswith((".pyc", ".pyo")):
            findings.append(
                Finding(
                    rule_id="hygiene.generated-artifact",
                    severity=GuardSeverity.ERROR,
                    category=GuardCategory.HYGIENE,
                    message="Generated/cache artifact should not be committed.",
                    file_path=path,
                )
            )

    for changed in snapshot.changed_lines:
        content = changed.content
        if _PRIVATE_KEY.search(content):
            findings.append(Finding(
                rule_id="security.private-key",
                severity=GuardSeverity.BLOCKER,
                category=GuardCategory.SECURITY,
                message="Private key material detected in changed content.",
                file_path=changed.file_path,
                line_number=changed.line_number,
            ))
        if _AWS_KEY.search(content):
            findings.append(Finding(
                rule_id="security.aws-access-key",
                severity=GuardSeverity.BLOCKER,
                category=GuardCategory.SECURITY,
                message="AWS access key pattern detected in changed content.",
                file_path=changed.file_path,
                line_number=changed.line_number,
            ))
        if _CONFLICT.search(content):
            findings.append(Finding(
                rule_id="hygiene.merge-conflict-marker",
                severity=GuardSeverity.BLOCKER,
                category=GuardCategory.HYGIENE,
                message="Unresolved Git merge-conflict marker detected.",
                file_path=changed.file_path,
                line_number=changed.line_number,
            ))
        if changed.file_path.endswith((".py", ".pyi")) and _PY_DEBUG.search(content):
            findings.append(Finding(
                rule_id="debug.python-breakpoint",
                severity=GuardSeverity.ERROR,
                category=GuardCategory.DEBUG,
                message="Python debugger/breakpoint left in changed code.",
                file_path=changed.file_path,
                line_number=changed.line_number,
            ))
        if changed.file_path.endswith((".js", ".jsx", ".ts", ".tsx")) and _JS_DEBUG.search(content):
            findings.append(Finding(
                rule_id="debug.javascript-debugger",
                severity=GuardSeverity.ERROR,
                category=GuardCategory.DEBUG,
                message="JavaScript/TypeScript debugger statement left in changed code.",
                file_path=changed.file_path,
                line_number=changed.line_number,
            ))

    source_changed = [p for p in snapshot.files if _suffix(p) in _SOURCE_SUFFIXES]
    test_changed = []
    for path in snapshot.files:
        normalized = path.lower().replace("\\", "/")
        test_path_parts = normalized.split("/")
        filename = test_path_parts[-1]
        is_test = (
            any(marker in test_path_parts for marker in _TEST_MARKERS)
            or filename.startswith("test_")
            or filename.endswith(
                ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
            )
        )
        if is_test:
            test_changed.append(path)
    if source_changed and not test_changed:
        findings.append(Finding(
            rule_id="testing.no-test-change",
            severity=GuardSeverity.INFO,
            category=GuardCategory.TESTING,
            message=(
                "Source changed without an accompanying test-file change; "
                "verify coverage intentionally."
            ),
        ))

    if len(snapshot.files) >= 25:
        findings.append(Finding(
            rule_id="changeset.large-file-count",
            severity=GuardSeverity.WARNING,
            category=GuardCategory.CHANGESET,
            message=(
                f"Large change set touches {len(snapshot.files)} files; "
                "consider splitting the change."
            ),
        ))

    return findings
