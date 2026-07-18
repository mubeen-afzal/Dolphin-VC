from datetime import UTC, datetime
from typing import Any

from app.services.connectors.base import Connector, NormalizedSignal
from app.types import SignalKind


class TavilyConnector(Connector):
    key = "tavily"
    requires_key = True

    @property
    def enabled(self) -> bool:
        return bool(self.settings.tavily_api_key)

    def normalize(self, raw: dict[str, Any]) -> NormalizedSignal:
        return NormalizedSignal(
            kind=SignalKind.PRESS,
            external_id=None,
            url=raw.get("url"),
            title=raw.get("title"),
            body=raw.get("content"),
            payload={"score": raw.get("score")},
            observed_at=datetime.now(UTC),
            strength=float(raw.get("score") or 0.5),
        )

    async def harvest(self, *, query: str, limit: int = 25) -> list[NormalizedSignal]:
        if not self.enabled:
            return []
        response = await self.client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": min(limit, 20),
            },
        )
        response.raise_for_status()
        return [self.normalize(item) for item in response.json().get("results", [])]
