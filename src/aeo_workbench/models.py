from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    model: str | None = None
    max_context_bytes: int = Field(default=60_000, ge=100, le=500_000)
    max_file_bytes: int = Field(default=30_000, ge=100, le=200_000)
    max_edits: int = Field(default=12, ge=1, le=50)
    max_output_tokens: int = Field(default=8000, ge=100, le=32000)
    input_per_million_usd: float | None = Field(default=None, ge=0)
    output_per_million_usd: float | None = Field(default=None, ge=0)
    gates: list[Gate] = Field(default_factory=list)


class Usage(Contract):
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    latency_ms: float = 0
    estimated_cost_usd: float | None = None
