# AEO v0.4.1 hotfix

Fixes:
- mypy type collision in `guardian/rules.py`
- mypy Optional assignment collisions in `guardian/service.py`
- Repo Guardian self-blocking on intentionally dangerous scanner fixtures in its own tests

Copy the contents of this archive to the repository root and replace the matching files.

Then run:

```powershell
python -m uv run ruff check .
python -m uv run mypy .
python -m uv run pytest
python -m uv run aeo guard
```

Do not restart the active engineering task. It should remain active.
