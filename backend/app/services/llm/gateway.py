import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.config import Settings
from app.db.models import LLMCall
from app.errors import AppError


class Purpose(StrEnum):
    EXTRACT = "extract"
    AXIS = "axis"
    MEMO = "memo"
    SEARCH = "search"
    VALIDATE = "validate"


@dataclass(frozen=True)
class LLMResult:
    content: str
    parsed: BaseModel | None
    provider: str
    model: str
    cached: bool
    cost_usd: float


class LLMGateway:
    def __init__(self, settings: Settings, session: AsyncSession | None = None) -> None:
        self.settings = settings
        self.session = session
        self.client = httpx.AsyncClient(timeout=settings.llm_request_timeout_s)

    async def _record(
        self,
        *,
        org_id: uuid.UUID | None,
        job_id: uuid.UUID | None,
        provider: str,
        model: str,
        purpose: Purpose,
        status: str,
        latency_ms: int,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if self.session is None:
            return
        usage = usage or {}
        self.session.add(
            LLMCall(
                org_id=org_id,
                job_id=job_id,
                provider=provider,
                model=model,
                purpose=purpose.value,
                status=status,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cost_usd=Decimal("0"),
                latency_ms=latency_ms,
                error=error,
            )
        )
        await self.session.flush()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=4),
        reraise=True,
    )
    async def _openai_compatible(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            }
        response = await self.client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def complete(
        self,
        *,
        purpose: Purpose,
        messages: list[dict[str, str]],
        schema: type[BaseModel] | None,
        org_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        max_tokens: int = 2048,
    ) -> LLMResult:
        providers = []
        if self.settings.openai_api_key:
            providers.append(
                (
                    "openai",
                    self.settings.openai_base_url,
                    self.settings.openai_api_key,
                    self.settings.openai_model_fast,
                )
            )
        if self.settings.nvidia_nim_api_key:
            providers.append(
                (
                    "nvidia_nim",
                    self.settings.nvidia_nim_base_url,
                    self.settings.nvidia_nim_api_key,
                    self.settings.nvidia_model_reasoning,
                )
            )
        if not providers:
            raise AppError(
                "SOURCE_UNAVAILABLE",
                "No LLM provider is configured; deterministic analysis remains available.",
                status_code=503,
                retryable=False,
            )
        errors: list[str] = []
        for provider, base_url, key, model in providers:
            started = time.perf_counter()
            try:
                payload = await self._openai_compatible(
                    base_url=base_url,
                    api_key=key,
                    model=model,
                    messages=messages,
                    schema=schema,
                    max_tokens=max_tokens,
                )
                content = payload["choices"][0]["message"]["content"]
                parsed = schema.model_validate(json.loads(content)) if schema else None
                latency = round((time.perf_counter() - started) * 1000)
                await self._record(
                    org_id=org_id,
                    job_id=job_id,
                    provider=provider,
                    model=model,
                    purpose=purpose,
                    status="ok",
                    latency_ms=latency,
                    usage=payload.get("usage"),
                )
                return LLMResult(content, parsed, provider, model, False, 0.0)
            except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
                latency = round((time.perf_counter() - started) * 1000)
                errors.append(f"{provider}: {type(exc).__name__}")
                await self._record(
                    org_id=org_id,
                    job_id=job_id,
                    provider=provider,
                    model=model,
                    purpose=purpose,
                    status="failed",
                    latency_ms=latency,
                    error=type(exc).__name__,
                )
        raise AppError(
            "UPSTREAM_ERROR",
            "Every configured LLM provider failed.",
            status_code=502,
            details={"providers": errors},
            retryable=True,
        )

    async def close(self) -> None:
        await self.client.aclose()
