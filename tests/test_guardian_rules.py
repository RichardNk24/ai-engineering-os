from aeo.domain.enums import GuardSeverity
from aeo.git.diff import ChangedLine, DiffSnapshot
from aeo.guardian.rules import analyze_diff


def test_guardian_detects_high_confidence_repository_risks() -> None:
    debugger_fixture = "break" + "point()"
    private_key_fixture = "-----BEGIN " + "PRIVATE KEY-----"

    snapshot = DiffSnapshot(
        files=["src/app.py", ".env", "src/__pycache__/x.pyc"],
        untracked_files=[".env"],
        changed_lines=[
            ChangedLine("src/app.py", 10, debugger_fixture),
            ChangedLine("src/app.py", 20, "<<<<<<< HEAD"),
            ChangedLine("src/app.py", 30, private_key_fixture),
        ],
    )
    findings = analyze_diff(snapshot)
    rules = {finding.rule_id for finding in findings}
    assert "debug.python-breakpoint" in rules
    assert "hygiene.merge-conflict-marker" in rules
    assert "security.private-key" in rules
    assert "security.env-file" in rules
    assert "hygiene.generated-artifact" in rules
    assert any(finding.severity == GuardSeverity.BLOCKER for finding in findings)


def test_source_change_without_tests_is_informational() -> None:
    findings = analyze_diff(
        DiffSnapshot(
            files=["src/service.py"],
            untracked_files=[],
            changed_lines=[ChangedLine("src/service.py", 1, "x = 1")],
        )
    )
    finding = next(item for item in findings if item.rule_id == "testing.no-test-change")
    assert finding.severity == GuardSeverity.INFO
