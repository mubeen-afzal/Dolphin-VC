from datetime import UTC, datetime
from typing import Any

from app.services.connectors.base import Connector, IdentityHint, NormalizedSignal
from app.types import SignalKind


class HackerNewsConnector(Connector):
    key = "hackernews"

    @property
    def enabled(self) -> bool:
        return True

    def normalize(self, raw: dict[str, Any]) -> NormalizedSignal:
        timestamp = raw.get("created_at")
        observed = (
            datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if timestamp
            else datetime.now(UTC)
        )
        author = raw.get("author")
        object_id = str(raw.get("objectID")) if raw.get("objectID") else None
        return NormalizedSignal(
            kind=SignalKind.LAUNCH_POST,
            external_id=object_id,
            url=raw.get("url")
            or (f"https://news.ycombinator.com/item?id={object_id}" if object_id else None),
            title=raw.get("title") or raw.get("story_title"),
            body=raw.get("story_text") or raw.get("comment_text"),
            payload={
                "points": raw.get("points") or 0,
                "comments": raw.get("num_comments") or 0,
                "author": author,
            },
            observed_at=observed,
            strength=min(1.0, 0.3 + (raw.get("points") or 0) / 500),
            identities=[IdentityHint("hackernews", author, 0.9)] if author else [],
        )

    async def harvest(self, *, query: str, limit: int = 25) -> list[NormalizedSignal]:
        payload = await self.get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": query, "tags": "story", "hitsPerPage": min(limit, 100)},
        )
        return [self.normalize(item) for item in payload.get("hits", [])]
