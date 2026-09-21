from types import SimpleNamespace

import pytest

from aeo_workbench.models import Proposal, Settings
from aeo_workbench.provider import OpenAIProvider
from aeo_workbench.safety import WorkbenchError


def test_sdk_contract_and_cost(monkeypatch):
    import openai

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def parse(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                status="completed",
                id="resp_test",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
                output_parsed=Proposal(summary="test", steps=[], risks=[], edits=[]),
            )

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    proposal, usage = OpenAIProvider().propose(
        "task",
        {"files": {}, "writable_paths": []},
        Settings(model="configured-model", input_per_million_usd=2, output_per_million_usd=8),
    )
    assert proposal.summary == "test"
    assert usage.estimated_cost_usd == pytest.approx(0.006)
    assert captured["request"]["store"] is False
    assert captured["request"]["text_format"] is Proposal
    assert captured["client"]["max_retries"] == 0


def test_missing_model_has_actionable_error():
    with pytest.raises(WorkbenchError, match="model"):
        OpenAIProvider().propose("task", {}, Settings())
