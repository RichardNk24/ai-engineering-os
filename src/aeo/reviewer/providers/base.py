from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aeo.reviewer.schemas import ReviewResponse, VerificationResponse


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderCallResult:
    payload: ReviewResponse | VerificationResponse
    usage: ProviderUsage
    request_id: str | None
    latency_ms: float


class ReviewProvider(Protocol):
    name: str

    def review(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> ProviderCallResult: ...

    def verify(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> ProviderCallResult: ...
