from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import (
    ChannelEdge,
    Company,
    FounderScore,
    FounderScoreEvent,
    Job,
    KBChunk,
    Org,
    Signal,
    Source,
    SourcingChannel,
)
from app.services.connectors.base import IdentityHint, NormalizedSignal
from app.services.ingestion import ensure_application_founder, resolve_outbound_signal
from app.services.utils import normalize_name, stable_hash
from app.types import JobStatus, OpportunityOrigin, SignalKind


@pytest.mark.integration
async def test_inbound_candidate_gets_a_cold_start_founder_profile(app) -> None:
    async with app.state.database.session_factory() as session:
        company = Company(name="Cold Start Co", normalized_name=normalize_name("Cold Start Co"))
        session.add(company)
        await session.flush()

        founder = await ensure_application_founder(
            session,
            company=company,
            contact_name=None,
            contact_email=None,
            website=None,
            artifacts=[],
        )
        await session.commit()

        score = await session.get(FounderScore, founder.id)
        assert founder.display_name == "Unresolved founder at Cold Start Co"
        assert founder.is_stub is True
        assert score is not None
        assert score.cold_start is True


@pytest.mark.integration
async def test_outbound_signal_becomes_a_deduplicated_candidate_with_memory(app) -> None:
    async with app.state.database.session_factory() as session:
        org = Org(name="Outbound Fund", slug="outbound-fund")
        session.add(org)
        source = await session.scalar(select(Source).where(Source.key == "github"))
        assert source is not None
        channel = SourcingChannel(key="github-test", label="GitHub test", kind="source")
        session.add(channel)
        await session.flush()
        signal = Signal(
            org_id=org.id,
            source_id=source.id,
            kind=SignalKind.REPO_ACTIVITY,
            external_id="42",
            url="https://github.com/founder/awesome-ai",
            title="founder/awesome-ai",
            body="Evidence-first diligence tooling.",
            payload={
                "stars": 125,
                "identity_hints": [
                    {"provider": "github", "value": "founder", "confidence": 1.0}
                ],
            },
            content_hash=stable_hash("outbound-signal"),
            strength=Decimal("0.80"),
            observed_at=datetime.now(UTC),
        )
        session.add(signal)
        await session.flush()

        first = await resolve_outbound_signal(
            session,
            app.state.settings,
            signal=signal,
            source_id=source.id,
            channel=channel,
        )
        second = await resolve_outbound_signal(
            session,
            app.state.settings,
            signal=signal,
            source_id=source.id,
            channel=channel,
        )
        await session.commit()

        assert first.opportunity_created is True
        assert second.opportunity_created is False
        assert first.opportunity.id == second.opportunity.id
        assert first.opportunity.origin == OpportunityOrigin.OUTBOUND
        assert first.person is not None
        assert first.person.links["identities"]["github"] == "founder"
        assert first.person.signal_count == 1
        assert await session.scalar(
            select(func.count(FounderScoreEvent.id)).where(
                FounderScoreEvent.person_id == first.person.id
            )
        ) == 3
        assert await session.scalar(select(func.count(KBChunk.id)).where(KBChunk.signal_id == signal.id)) == 1
        assert await session.scalar(
            select(func.count(ChannelEdge.id)).where(ChannelEdge.company_id == first.company.id)
        ) == 1


@pytest.mark.integration
async def test_harvest_queues_shared_screening_for_resolved_candidates(app, monkeypatch) -> None:
    from app.services import pipeline

    class FakeGitHubConnector:
        def __init__(self, settings) -> None:
            pass

        @property
        def enabled(self) -> bool:
            return True

        async def harvest(self, *, query: str, limit: int) -> list[NormalizedSignal]:
            return [
                NormalizedSignal(
                    kind=SignalKind.REPO_ACTIVITY,
                    external_id="harvested-1",
                    url="https://github.com/harvested/venture-tool",
                    title="harvested/venture-tool",
                    body="A public product artifact.",
                    payload={"stars": 90},
                    observed_at=datetime.now(UTC),
                    strength=0.75,
                    identities=[IdentityHint("github", "harvested")],
                )
            ]

        async def close(self) -> None:
            pass

    monkeypatch.setattr(pipeline, "GitHubConnector", FakeGitHubConnector)
    original_demo_mode = app.state.settings.demo_mode
    app.state.settings.demo_mode = False
    try:
        async with app.state.database.session_factory() as session:
            org = Org(name="Harvest Fund", slug="harvest-fund")
            session.add(org)
            await session.flush()
            job = Job(
                org_id=org.id,
                kind="ingest.harvest",
                status=JobStatus.RUNNING,
                target_type="organization",
                target_id=org.id,
                input={"channels": ["github"], "query": "venture", "limit": 1},
            )
            session.add(job)
            await session.commit()

            child_job_ids = await pipeline._process_harvest(session, app.state.settings, job)

            assert len(child_job_ids) == 1
            screen_job = await session.get(Job, child_job_ids[0])
            assert screen_job is not None
            assert screen_job.kind == "screen"
            assert screen_job.status == JobStatus.QUEUED
            assert job.result["candidates_resolved"] == 1
    finally:
        app.state.settings.demo_mode = original_demo_mode
