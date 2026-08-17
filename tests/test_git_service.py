from pathlib import Path

from aeo.git.service import collect_git_context


def test_collect_git_context_outside_repository(tmp_path: Path) -> None:
    context = collect_git_context(tmp_path)

    assert context.is_repository is False
    assert context.branch is None
    assert context.commit_sha is None
    assert context.changed_files == 0
