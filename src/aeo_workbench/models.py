import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, hide_input_in_errors=True)


class Edit(Contract):
    path: str
    operation: Literal["write", "delete"]
    content: str


class Proposal(Contract):
    summary: str
    steps: list[str]
    risks: list[str]
    edits: list[Edit]


class Gate(Contract):
    name: str = Field(min_length=1, max_length=80)
    argv: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class Settings(Contract):
    schema_version: Literal[1] = 1
    require_pipeline: bool = True
    review_model: str | None = None
    bridge_timeout_seconds: int = Field(default=600, ge=10, le=3600)
    model: str | None = None
    max_context_bytes: int = Field(default=60_000, ge=100, le=500_000)
    max_file_bytes: int = Field(default=30_000, ge=100, le=200_000)
    max_edits: int = Field(default=12, ge=1, le=50)
    max_output_tokens: int = Field(default=8000, ge=100, le=32000)
    input_per_million_usd: float | None = Field(default=None, ge=0)
    output_per_million_usd: float | None = Field(default=None, ge=0)
    gates: list[Gate] = Field(default_factory=list)

    @field_validator("model", "review_model")
    @classmethod
    def model_identifier(cls, value: str | None) -> str | None:
        if value is not None and (
            value.lower().startswith("sk-")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}", value)
        ):
            raise ValueError("Expected a model identifier, never an API key.")
        return value


class Usage(Contract):
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    latency_ms: float = 0
    estimated_cost_usd: float | None = None
