"""Canonical inbound and outbound candidate ingestion.

Both application submissions and harvested signals must converge before they are
screened.  Keeping this work here makes the pipeline responsible for analysis,
not for reconstructing identities ad hoc in every connector.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    Affiliation,
    ChannelEdge,
    Company,
    FounderScoreEvent,
    KBChunk,
    Opportunity,
    Person,
    Signal,
    SourcingChannel,
)
from app.services.founders import recompute_founder_score
from app.services.utils import normalize_name, stable_hash, utcnow
from app.types import OpportunityOrigin, OpportunityStage, SignalKind


@dataclass(frozen=True)
class ResolvedSignal:
    person: Person | None
    company: Company
    opportunity: Opportunity
    opportunity_created: bool


def _clean_name(value: str | None, *, fallback: str) -> str:
    cleaned = " ".join((value or "").split()).strip()
    return cleaned[:200] if cleaned else fallback[:200]


def _identity_hints(signal: Signal) -> list[dict[str, Any]]:
    raw = signal.payload.get("identity_hints", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("value")]


def _identity_link(provider: str, value: str) -> str | None:
    if provider == "github":
        return f"https://github.com/{value}"
    if provider == "hackernews":
        return f"https://news.ycombinator.com/user?id={value}"
    return None


async def _person_by_identity(
    session: AsyncSession, provider: str, value: str
) -> Person | None:
    normalized = normalize_name(value)
    candidates = (
        await session.scalars(
            select(Person).where(Person.merged_into_id.is_(None)).order_by(Person.created_at)
        )
    ).all()
    for person in candidates:
        links = person.links or {}
        if str(links.get(provider, "")).casefold() == value.casefold():
            return person
        identities = links.get("identities", {})
        if isinstance(identities, dict) and str(identities.get(provider, "")).casefold() == value.casefold():
            return person
    if normalized:
        matched_person = await session.scalar(
            select(Person).where(
                Person.normalized_name == normalized, Person.merged_into_id.is_(None)
            )
        )
        return matched_person
    return None


async def _ensure_affiliation(
    session: AsyncSession, *, person: Person, company: Company, confidence: float
) -> None:
    existing = await session.scalar(
        select(Affiliation).where(
            Affiliation.person_id == person.id,
            Affiliation.company_id == company.id,
            Affiliation.role == "founder",
        )
    )
    if existing is None:
        session.add(
            Affiliation(
                person_id=person.id,
                company_id=company.id,
                role="founder",
                is_founder=True,
                confidence=Decimal(str(confidence)),
            )
        )
    else:
        existing.is_founder = True
        existing.confidence = max(existing.confidence, Decimal(str(confidence)))


async def ensure_application_founder(
    session: AsyncSession,
    *,
    company: Company,
    contact_name: str | None,
    contact_email: str | None,
    website: str | None,
    artifacts: list[str],
) -> Person:
    """Create a cold-start founder record for every inbound candidate.

    The fallback identity intentionally says that it is unresolved.  It preserves
    the candidate record and allows a reviewer to correct it later without
    pretending the company name is a person's identity.
    """

    email = contact_email.casefold() if contact_email else None
    person = None
    if email:
        people = (
            await session.scalars(select(Person).where(Person.merged_into_id.is_(None)))
        ).all()
        person = next((item for item in people if email in {value.casefold() for value in item.emails}), None)
    display_name = _clean_name(contact_name, fallback=f"Unresolved founder at {company.name}")
    if person is None:
        normalized = normalize_name(display_name)
        person = await session.scalar(
            select(Person).where(
                Person.normalized_name == normalized,
                Person.merged_into_id.is_(None),
            )
        )
    if person is None:
        links: dict[str, Any] = {}
        if website:
            links["website"] = website
        if artifacts:
            links["work_samples"] = artifacts[:10]
        person = Person(
            display_name=display_name,
            normalized_name=normalize_name(display_name),
            emails=[email] if email else [],
            links=links,
            is_stub=not bool(contact_name or contact_email),
        )
        session.add(person)
        await session.flush()
    elif email and email not in {value.casefold() for value in person.emails}:
        person.emails = [*person.emails, email]

    await _ensure_affiliation(session, person=person, company=company, confidence=0.35)
    await session.flush()
    # A founder-provided work sample is useful context, but deliberately carries
    # little weight until the normal diligence workflow independently verifies it.
    if artifacts:
        has_event = await session.scalar(
            select(FounderScoreEvent.id).where(
                FounderScoreEvent.person_id == person.id,
                FounderScoreEvent.reason == "Founder supplied work samples pending verification.",
            )
        )
        if has_event is None:
            session.add(
                FounderScoreEvent(
                    person_id=person.id,
                    component="execution",
                    delta=Decimal("55"),
                    weight=Decimal("0.150"),
                    reason="Founder supplied work samples pending verification.",
                    occurred_at=utcnow(),
                )
            )
    await session.flush()
    await recompute_founder_score(session, person.id)
    return person


def _company_name_from_signal(signal: Signal) -> str:
    explicit = signal.payload.get("company_name")
    if isinstance(explicit, str) and explicit.strip():
        return _clean_name(explicit, fallback="Discovered company")
    if signal.kind == SignalKind.REPO_ACTIVITY and signal.title:
        return _clean_name(signal.title.rsplit("/", 1)[-1], fallback="Discovered repository")
    title = _clean_name(signal.title, fallback="")
    if title:
        for prefix in ("Show HN:", "Launch HN:"):
            if title.casefold().startswith(prefix.casefold()):
                title = title[len(prefix) :].strip()
        return title
    hostname = urlsplit(signal.url or "").hostname
    return _clean_name(hostname, fallback="Discovered company")


def _company_domain(signal: Signal) -> str | None:
    hostname = (urlsplit(signal.url or "").hostname or "").casefold()
    if not hostname or hostname in {"github.com", "arxiv.org", "news.ycombinator.com"}:
        return None
    return hostname


async def _ensure_company(session: AsyncSession, signal: Signal) -> Company:
    name = _company_name_from_signal(signal)
    domain = _company_domain(signal)
    company = None
    if domain:
        company = await session.scalar(
            select(Company).where(Company.domain == domain, Company.merged_into_id.is_(None))
        )
    if company is None:
        company = await session.scalar(
            select(Company).where(
                Company.normalized_name == normalize_name(name),
                Company.merged_into_id.is_(None),
            )
        )
    if company is None:
        links = {"source": signal.url} if signal.url else {}
        company = Company(
            name=name,
            normalized_name=normalize_name(name),
            domain=domain,
            links=links,
            one_liner=(signal.body or signal.title or "")[:500] or None,
            is_stub=False,
        )
        session.add(company)
        await session.flush()
    company.last_signal_at = max(
        (company.last_signal_at, signal.observed_at), key=lambda item: item.timestamp()
    ) if company.last_signal_at else signal.observed_at
    return company


async def _ensure_signal_person(session: AsyncSession, signal: Signal) -> Person | None:
    hints = _identity_hints(signal)
    if not hints:
        return None
    hint = max(hints, key=lambda item: float(item.get("confidence", 0)))
    provider = str(hint.get("provider", "unknown"))
    value = _clean_name(str(hint["value"]), fallback="Unknown founder")
    person = await _person_by_identity(session, provider, value)
    if person is None:
        identities = {provider: value}
        links: dict[str, Any] = {"identities": identities}
        link = _identity_link(provider, value)
        if link:
            links[provider] = link
        person = Person(
            display_name=value,
            normalized_name=normalize_name(value),
            links=links,
            is_stub=provider in {"github", "hackernews"},
        )
        session.add(person)
        await session.flush()
    if signal.person_id != person.id:
        person.last_signal_at = max(
            (person.last_signal_at, signal.observed_at), key=lambda item: item.timestamp()
        ) if person.last_signal_at else signal.observed_at
        person.signal_count += 1
        person.source_count += 1
    return person


def _score_events_for(signal: Signal) -> list[tuple[str, Decimal, Decimal, str]]:
    if signal.kind == SignalKind.REPO_ACTIVITY:
        stars = int(signal.payload.get("stars") or 0)
        return [
            ("execution", Decimal("62"), Decimal("0.80"), "Public repository activity."),
            ("technical_depth", Decimal("68"), Decimal("0.80"), "Public technical artifact."),
            (
                "validation",
                Decimal(str(min(82, 42 + stars // 25))),
                Decimal("0.65"),
                "Repository adoption signal.",
            ),
        ]
    if signal.kind == SignalKind.PAPER:
        return [
            ("technical_depth", Decimal("76"), Decimal("0.85"), "Published research artifact."),
            ("domain_expertise", Decimal("70"), Decimal("0.75"), "Research domain evidence."),
        ]
    if signal.kind in {SignalKind.LAUNCH_POST, SignalKind.PRESS}:
        return [
            ("communication", Decimal("58"), Decimal("0.45"), "Public launch communication."),
            ("execution", Decimal("54"), Decimal("0.45"), "Public product-launch evidence."),
        ]
    return []


async def _record_founder_events(session: AsyncSession, person: Person, signal: Signal) -> None:
    for component, delta, weight, reason in _score_events_for(signal):
        existing = await session.scalar(
            select(FounderScoreEvent.id).where(
                FounderScoreEvent.person_id == person.id,
                FounderScoreEvent.signal_id == signal.id,
                FounderScoreEvent.component == component,
            )
        )
        if existing is None:
            session.add(
                FounderScoreEvent(
                    person_id=person.id,
                    component=component,
                    delta=delta,
                    weight=weight,
                    reason=reason,
                    signal_id=signal.id,
                    occurred_at=signal.observed_at,
                )
            )
    await session.flush()
    await recompute_founder_score(session, person.id)


async def _record_memory(
    session: AsyncSession,
    *,
    signal: Signal,
    source_id: uuid.UUID,
    person: Person | None,
    company: Company,
    channel: SourcingChannel | None,
) -> None:
    content = "\n".join(part for part in [signal.title, signal.body] if part).strip()
    if content:
        exists = await session.scalar(select(KBChunk.id).where(KBChunk.signal_id == signal.id))
        if exists is None:
            session.add(
                KBChunk(
                    org_id=signal.org_id,
                    scope="signal",
                    person_id=person.id if person else None,
                    company_id=company.id,
                    signal_id=signal.id,
                    chunk_index=0,
                    title=signal.title,
                    content=content,
                    content_hash=stable_hash({"signal_id": signal.id, "content": content}),
                    token_count=len(content.split()),
                    source_id=source_id,
                    source_url=signal.url,
                    observed_at=signal.observed_at,
                )
            )
    if channel is not None:
        edge = await session.scalar(
            select(ChannelEdge).where(
                ChannelEdge.channel_id == channel.id,
                ChannelEdge.person_id == (person.id if person else None),
                ChannelEdge.company_id == company.id,
            )
        )
        if edge is None:
            session.add(
                ChannelEdge(
                    channel_id=channel.id,
                    person_id=person.id if person else None,
                    company_id=company.id,
                    weight=signal.strength or Decimal("0.5"),
                )
            )


async def resolve_outbound_signal(
    session: AsyncSession,
    settings: Settings,
    *,
    signal: Signal,
    source_id: uuid.UUID,
    channel: SourcingChannel | None,
) -> ResolvedSignal:
    """Resolve one harvested signal into durable candidate records and memory."""

    company = await _ensure_company(session, signal)
    person = await _ensure_signal_person(session, signal)
    signal.company_id = company.id
    if person:
        signal.person_id = person.id
        await _ensure_affiliation(session, person=person, company=company, confidence=0.65)
        await _record_founder_events(session, person, signal)
    await _record_memory(
        session,
        signal=signal,
        source_id=source_id,
        person=person,
        company=company,
        channel=channel,
    )
    opportunity = await session.scalar(
        select(Opportunity).where(
            Opportunity.org_id == signal.org_id,
            Opportunity.company_id == company.id,
            Opportunity.stage != OpportunityStage.ARCHIVED,
        )
    )
    created = opportunity is None
    if opportunity is None:
        now = utcnow()
        opportunity = Opportunity(
            org_id=signal.org_id,
            company_id=company.id,
            origin=OpportunityOrigin.OUTBOUND,
            title=company.name,
            first_signal_at=signal.observed_at,
            sla_deadline_at=now + timedelta(hours=settings.decision_sla_hours),
            dedupe_key=f"{signal.org_id}:{company.id}",
        )
        session.add(opportunity)
        if channel is not None:
            channel.advanced_count += 1
    await session.flush()
    return ResolvedSignal(
        person=person,
        company=company,
        opportunity=opportunity,
        opportunity_created=created,
    )
