import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.config import Settings
from app.services.utils import stable_hash
from app.types import SignalKind


@dataclass(frozen=True)
class IdentityHint:
    provider: str
    value: str
    confidence: float = 1.0


@dataclass(frozen=True)
class NormalizedSignal:
    kind: SignalKind
    external_id: str | None
    url: str | None
    title: str | None
    body: str | None
    payload: dict[str, Any]
    observed_at: datetime
    strength: float
    identities: list[IdentityHint] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        return stable_hash(
            {
                "kind": self.kind,
                "url": self.url,
                "title": self.title,
                "body": self.body,
                "payload": self.payload,
            }
        )


class Connector(abc.ABC):
    key: str
    requires_key: bool = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, read=20, write=20, pool=5),
            headers={"User-Agent": settings.user_agent},
            follow_redirects=False,
        )

    @property
    @abc.abstractmethod
    def enabled(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    async def harvest(self, *, query: str, limit: int = 25) -> list[NormalizedSignal]:
        raise NotImplementedError

    @abc.abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NormalizedSignal:
        raise NotImplementedError

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=4),
        reraise=True,
    )
    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.client.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self.client.aclose()
