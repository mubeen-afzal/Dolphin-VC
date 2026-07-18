from datetime import UTC, datetime
from typing import Any

from app.services.connectors.base import Connector, IdentityHint, NormalizedSignal
from app.types import SignalKind


class ArxivConnector(Connector):
    key = "arxiv"

    @property
    def enabled(self) -> bool:
        return True

    def normalize(self, raw: dict[str, Any]) -> NormalizedSignal:
        published = raw.get("published")
        observed = (
            datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            if published
            else datetime.now(UTC)
        )
        authors = [str(item) for item in raw.get("authors", [])]
        return NormalizedSignal(
            kind=SignalKind.PAPER,
            external_id=raw.get("id"),
            url=raw.get("url"),
            title=raw.get("title"),
            body=raw.get("summary"),
            payload={"authors": authors, "categories": raw.get("categories", [])},
            observed_at=observed,
            strength=0.65,
            identities=[IdentityHint("author_name", author, 0.45) for author in authors],
        )

    async def harvest(self, *, query: str, limit: int = 25) -> list[NormalizedSignal]:
        # The service deliberately keeps XML parsing outside the shared fetcher's JSON path.
        response = await self.client.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "start": 0, "max_results": min(limit, 100)},
        )
        response.raise_for_status()
        from defusedxml import ElementTree as ET  # type: ignore[import-untyped]

        root = ET.fromstring(response.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        rows = []
        for entry in root.findall("a:entry", ns):
            identifier = entry.findtext("a:id", namespaces=ns)
            rows.append(
                {
                    "id": identifier,
                    "url": identifier,
                    "title": (entry.findtext("a:title", namespaces=ns) or "").strip(),
                    "summary": (entry.findtext("a:summary", namespaces=ns) or "").strip(),
                    "published": entry.findtext("a:published", namespaces=ns),
                    "authors": [
                        node.findtext("a:name", namespaces=ns)
                        for node in entry.findall("a:author", ns)
                    ],
                    "categories": [
                        node.attrib.get("term") for node in entry.findall("a:category", ns)
                    ],
                }
            )
        return [self.normalize(item) for item in rows]
