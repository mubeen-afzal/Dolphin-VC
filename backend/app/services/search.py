import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Company, KBChunk, Opportunity
from app.schemas.opportunity import OpportunityCard
from app.schemas.search import (
    OpportunityMatch,
    OpportunitySearchItem,
    OpportunitySearchResponse,
    SearchInterpretation,
)
from app.services.opportunities import build_card

SECTOR_ALIASES = {
    "ai infra": "ai_infra",
    "ai infrastructure": "ai_infra",
    "devtools": "devtools",
    "developer tools": "devtools",
    "fintech": "fintech",
    "healthtech": "healthtech",
    "climate": "climate",
    "robotics": "robotics",
    "defense": "defense",
    "vertical saas": "vertical_saas",
}
COUNTRY_ALIASES = {
    "berlin": ("DE", "Berlin"),
    "germany": ("DE", None),
    "london": ("GB", "London"),
    "uk": ("GB", None),
    "united states": ("US", None),
    "san francisco": ("US", "San Francisco"),
}


@dataclass(frozen=True)
class QueryPlan:
    filters: dict[str, Any]
    residual: str
    unresolved: list[str]
    confidence: float


def interpret_query(query: str) -> QueryPlan:
    folded = query.casefold()
    filters: dict[str, Any] = {}
    matched_phrases: set[str] = set()
    sectors = []
    for phrase, sector in SECTOR_ALIASES.items():
        if phrase in folded:
            sectors.append(sector)
            matched_phrases.add(phrase)
    if sectors:
        filters["sectors"] = sorted(set(sectors))
    for phrase, (country, city) in COUNTRY_ALIASES.items():
        if phrase in folded:
            filters["country"] = country
            if city:
                filters["city"] = city
            matched_phrases.add(phrase)
            break
    if "technical founder" in folded or "engineer founder" in folded:
        filters["founder_profile"] = ["technical"]
        matched_phrases.add("technical founder")
    if "enterprise traction" in folded or "b2b traction" in folded:
        filters["traction_type"] = ["enterprise"]
        matched_phrases.add("enterprise traction")
    if "no prior vc" in folded or "no vc backing" in folded or "bootstrapped" in folded:
        filters["prior_vc_backing"] = False
        matched_phrases.update({"no prior vc", "no vc backing", "bootstrapped"})
    if "top-tier accelerator" in folded or "top tier accelerator" in folded:
        filters["accelerator_tier"] = ["top"]
        matched_phrases.update({"top-tier accelerator", "top tier accelerator"})
    residual = folded
    for phrase in sorted(matched_phrases, key=len, reverse=True):
        residual = residual.replace(phrase, " ")
    residual = re.sub(r"\s+", " ", residual).strip(" ,") or query
    confidence = min(0.95, 0.45 + 0.08 * len(filters))
    return QueryPlan(filters, residual, [], round(confidence, 2))


def _match_company(
    company: Company, plan: QueryPlan
) -> tuple[float, list[dict[str, Any]], list[str]]:
    matched: list[dict[str, Any]] = []
    unmatched: list[str] = []
    points = 0.0
    total = max(1, len(plan.filters))
    sectors = set(company.sectors or [])
    for attribute, value in plan.filters.items():
        ok = True
        why = ""
        if attribute == "sectors":
            ok = bool(sectors & set(value))
            why = f"Company sectors: {', '.join(company.sectors)}"
        elif attribute == "country":
            ok = company.hq_country == value
            why = f"HQ country: {company.hq_country or 'not disclosed'}"
        elif attribute == "city":
            ok = (company.hq_city or "").casefold() == str(value).casefold()
            why = f"HQ city: {company.hq_city or 'not disclosed'}"
        else:
            text = " ".join(filter(None, [company.one_liner, company.description])).casefold()
            terms = value if isinstance(value, list) else [str(value)]
            ok = any(str(term).replace("_", " ") in text for term in terms)
            why = f"Matched against available company evidence for {attribute}."
        if ok:
            points += 1
            matched.append({"attribute": attribute, "evidence_id": None, "why": why})
        else:
            unmatched.append(attribute)
    return points / total, matched, unmatched


async def search_opportunities(
    session: AsyncSession,
    settings: Settings,
    org_id: uuid.UUID,
    *,
    q: str,
    limit: int,
) -> OpportunitySearchResponse:
    started = time.perf_counter()
    plan = interpret_query(q)
    query = select(Opportunity, Company).join(Company).where(Opportunity.org_id == org_id)
    if plan.filters.get("country"):
        query = query.where(Company.hq_country == plan.filters["country"])
    if plan.filters.get("city"):
        query = query.where(Company.hq_city.ilike(plan.filters["city"]))
    rows = (await session.execute(query.limit(200))).all()
    ranked = []
    residual_terms = [item for item in re.findall(r"[a-z0-9]+", plan.residual) if len(item) > 2]
    for opportunity, company in rows:
        filter_score, matched, unmatched = _match_company(company, plan)
        text = " ".join(
            filter(None, [company.name, company.one_liner, company.description])
        ).casefold()
        lexical = sum(term in text for term in residual_terms) / max(1, len(residual_terms))
        score = 0.75 * filter_score + 0.25 * lexical
        ranked.append((score, opportunity, matched, unmatched))
    ranked.sort(key=lambda item: item[0], reverse=True)
    items = []
    for score, opportunity, matched, unmatched in ranked[:limit]:
        card: OpportunityCard = await build_card(session, settings, opportunity)
        items.append(
            OpportunitySearchItem(
                opportunity=card,
                match=OpportunityMatch(score=round(score, 3), matched=matched, unmatched=unmatched),
            )
        )
    return OpportunitySearchResponse(
        interpreted=SearchInterpretation(
            filters=plan.filters,
            residual_semantic=plan.residual,
            unresolved=plan.unresolved,
            confidence=plan.confidence,
        ),
        items=items,
        took_ms=round((time.perf_counter() - started) * 1000),
        used_llm=False,
        degraded=False,
    )


async def search_kb(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    q: str,
    company_id: uuid.UUID | None,
    person_id: uuid.UUID | None,
    k: int,
) -> list[dict[str, Any]]:
    query = select(KBChunk).where(or_(KBChunk.org_id == org_id, KBChunk.org_id.is_(None)))
    if company_id:
        query = query.where(KBChunk.company_id == company_id)
    if person_id:
        query = query.where(KBChunk.person_id == person_id)
    terms = [term for term in re.findall(r"\w+", q.casefold()) if len(term) > 2]
    rows = (await session.scalars(query.limit(500))).all()
    scored = []
    for row in rows:
        text = row.content.casefold()
        score = sum(term in text for term in terms) / max(1, len(terms))
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": str(row.id),
            "content": row.content,
            "source": str(row.source_id) if row.source_id else None,
            "url": row.source_url,
            "observed_at": row.observed_at,
            "score": round(score, 3),
            "locator": {
                "document_id": str(row.document_id) if row.document_id else None,
                "page": row.page_no,
            },
        }
        for score, row in scored[:k]
    ]
