from aeo.git.diff import _parse_unified_zero


def test_parse_unified_zero_tracks_new_line_numbers() -> None:
    debugger_fixture = "break" + "point()"
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,0 +2,2 @@\n"
        f"+{debugger_fixture}\n"
        "+x = 2\n"
    )
    files, lines = _parse_unified_zero(diff)
    assert files == ["a.py"]
    assert [(line.line_number, line.content) for line in lines] == [
        (2, debugger_fixture),
        (3, "x = 2"),
    ]
