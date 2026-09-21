from __future__ import annotations

import importlib
from time import perf_counter
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from aeo.reviewer.providers.base import ProviderCallResult, ProviderUsage
from aeo.reviewer.schemas import ReviewResponse, VerificationResponse

T = TypeVar("T", bound=BaseModel)


class OpenAIReviewProvider:
    name = "openai"

    def __init__(self) -> None:
        try:
            module = importlib.import_module("openai")
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI reviewer support is not installed. Run "
                "`python -m uv sync --extra dev --extra ai`."
            ) from exc
        self._client: Any = module.OpenAI()

    def _parse(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        max_output_tokens: int,
    ) -> tuple[T, ProviderUsage, str | None, float]:
        started = perf_counter()
        response = self._client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=schema,
            max_output_tokens=max_output_tokens,
        )
        latency_ms = (perf_counter() - started) * 1000

        parsed: T | None = None
        for output in response.output:
            if output.type != "message":
                continue
            for item in output.content:
                if item.type == "output_text" and item.parsed is not None:
                    parsed = cast(T, item.parsed)
                    break
            if parsed is not None:
                break

        if parsed is None:
            raise RuntimeError("The OpenAI response did not contain parseable structured output.")

        usage_obj: Any = getattr(response, "usage", None)
        usage = ProviderUsage(
            input_tokens=int(getattr(usage_obj, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage_obj, "output_tokens", 0) or 0),
        )
        return parsed, usage, getattr(response, "id", None), latency_ms

    def review(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> ProviderCallResult:
        payload, usage, request_id, latency_ms = self._parse(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=ReviewResponse,
            max_output_tokens=max_output_tokens,
        )
        return ProviderCallResult(payload, usage, request_id, latency_ms)

    def verify(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> ProviderCallResult:
        payload, usage, request_id, latency_ms = self._parse(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=VerificationResponse,
            max_output_tokens=max_output_tokens,
        )
        return ProviderCallResult(payload, usage, request_id, latency_ms)
