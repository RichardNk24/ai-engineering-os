from pathlib import Path

from fastapi.testclient import TestClient

from aeo.api.main import app
from aeo.project.configuration import initialize_project


def test_reviews_endpoint_is_available(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='review-api'\n",
        encoding="utf-8",
    )
    initialize_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    response = client.get("/reviews")

    assert response.status_code == 200
    assert response.json() == []
