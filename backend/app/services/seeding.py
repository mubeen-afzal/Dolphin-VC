from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Source
from app.types import SourceStatus, SourceTier

SOURCE_CATALOGUE: list[dict[str, Any]] = [
    {
        "key": "deck",
        "display_name": "Founder-submitted deck",
        "tier": SourceTier.SELF_REPORTED,
        "base_url": None,
        "reliability": Decimal("0.400"),
        "requires_key": False,
        "tos_note": "Submitted with founder consent.",
    },
    {
        "key": "github",
        "display_name": "GitHub",
        "tier": SourceTier.PRIMARY,
        "base_url": "https://api.github.com",
        "reliability": Decimal("0.920"),
        "requires_key": False,
        "tos_note": "Official public API only.",
    },
    {
        "key": "hackernews",
        "display_name": "Hacker News / Algolia",
        "tier": SourceTier.SELF_REPORTED,
        "base_url": "https://hn.algolia.com/api/v1",
        "reliability": Decimal("0.550"),
        "requires_key": False,
        "tos_note": "Public Algolia endpoint.",
    },
    {
        "key": "arxiv",
        "display_name": "arXiv",
        "tier": SourceTier.PRIMARY,
        "base_url": "https://export.arxiv.org/api",
        "reliability": Decimal("0.900"),
        "requires_key": False,
        "tos_note": "Official API with polite request rate.",
    },
    {
        "key": "tavily",
        "display_name": "Tavily Web Search",
        "tier": SourceTier.AGGREGATOR,
        "base_url": "https://api.tavily.com",
        "reliability": Decimal("0.650"),
        "requires_key": True,
        "tos_note": "Search API; individual result provenance is retained.",
    },
]


async def seed_reference_data(session: AsyncSession, settings: Settings) -> None:
    existing = set((await session.scalars(select(Source.key))).all())
    for definition in SOURCE_CATALOGUE:
        if definition["key"] in existing:
            continue
        status = SourceStatus.ACTIVE
        if definition["key"] == "tavily" and not settings.tavily_api_key:
            status = SourceStatus.NO_CREDENTIALS
        session.add(Source(**definition, status=status, rate_limit={}))
    await session.commit()
