import asyncio
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.db.models import (
    Affiliation,
    Claim,
    Company,
    Evidence,
    FounderScoreEvent,
    Memo,
    Opportunity,
    OpportunityScore,
    Org,
    Person,
    Source,
    Thesis,
    User,
)
from app.db.session import Database
from app.services.auth import hash_password
from app.services.founders import recompute_founder_score
from app.services.memo import compose_memo
from app.services.seeding import seed_reference_data
from app.services.utils import normalize_name, utcnow
from app.types import (
    AxisKind,
    ClaimCategory,
    ClaimStatus,
    DecisionKind,
    OpportunityOrigin,
    OpportunityStage,
    SourceTier,
    TrendKind,
    UserRole,
)


async def seed() -> None:
    settings = get_settings()
    database = Database(settings)
    async with database.session_factory() as session:
        await seed_reference_data(session, settings)
        existing = await session.scalar(select(Org).where(Org.slug == "demo-fund"))
        if existing:
            print("Demo seed already exists: demo@vcbrain.dev / Demo-password-42!")
            await database.dispose()
            return

        org = Org(name="VC Brain Demo Fund", slug="demo-fund")
        session.add(org)
        await session.flush()
        user = User(
            org_id=org.id,
            email="demo@vcbrain.dev",
            password_hash=hash_password("Demo-password-42!"),
            full_name="Demo Partner",
            role=UserRole.OWNER,
            email_verified_at=utcnow(),
        )
        thesis = Thesis(
            org_id=org.id,
            name="DACH pre-seed AI",
            is_default=True,
            sectors=["ai_infra", "devtools"],
            stages=["pre_seed", "seed"],
            geos=["DE", "DACH", "remote"],
            check_size_min=Decimal("50000"),
            check_size_max=Decimal("150000"),
            currency="USD",
            must_haves=["technical founder", "proof of work"],
            deal_breakers=["services-only business"],
        )
        company = Company(
            name="Nullpoint",
            normalized_name=normalize_name("Nullpoint"),
            domain="nullpoint.example",
            one_liner="Deterministic replay for distributed AI systems",
            description="Infrastructure that helps engineering teams reproduce production failures.",
            sectors=["devtools", "ai_infra"],
            stage="pre_seed",
            hq_country="DE",
            hq_city="Berlin",
        )
        founder = Person(
            display_name="Lea Marquez",
            normalized_name=normalize_name("Lea Marquez"),
            headline="Distributed systems engineer",
            country_code="DE",
            city="Berlin",
            skills=["rust", "distributed_systems", "ai_infra"],
            links={"github": "https://github.com/example"},
            signal_count=4,
            source_count=3,
        )
        session.add_all([user, thesis, company, founder])
        await session.flush()
        session.add(
            Affiliation(
                person_id=founder.id,
                company_id=company.id,
                role="founder",
                is_founder=True,
                confidence=Decimal("0.950"),
            )
        )
        now = utcnow()
        session.add_all(
            [
                FounderScoreEvent(
                    person_id=founder.id,
                    component="execution",
                    delta=Decimal("82"),
                    reason="Shipped three public releases.",
                    occurred_at=now - timedelta(days=20),
                ),
                FounderScoreEvent(
                    person_id=founder.id,
                    component="technical_depth",
                    delta=Decimal("88"),
                    reason="Maintains a technically deep systems project.",
                    occurred_at=now - timedelta(days=35),
                ),
                FounderScoreEvent(
                    person_id=founder.id,
                    component="validation",
                    delta=Decimal("70"),
                    reason="Won a public infrastructure hackathon.",
                    occurred_at=now - timedelta(days=60),
                ),
            ]
        )
        await session.flush()
        await recompute_founder_score(session, founder.id)

        opportunity = Opportunity(
            org_id=org.id,
            company_id=company.id,
            thesis_id=thesis.id,
            origin=OpportunityOrigin.OUTBOUND,
            stage=OpportunityStage.DECISION,
            title=company.name,
            thesis_fit=Decimal("78"),
            conviction=Decimal("81"),
            priority_rank=Decimal("91"),
            first_signal_at=now - timedelta(hours=5),
            sourced_at=now - timedelta(hours=5),
            screened_at=now - timedelta(hours=3),
            memo_ready_at=now - timedelta(minutes=20),
            sla_deadline_at=now + timedelta(hours=19),
            dedupe_key=f"{org.id}:{company.id}",
        )
        session.add(opportunity)
        await session.flush()
        axis_rows = [
            (AxisKind.FOUNDER, "81", "0.710", "Founder has repeated primary proof of work."),
            (AxisKind.MARKET, "64", "0.550", "Large market but dense competition."),
            (AxisKind.IDEA_VS_MARKET, "73.5", "0.490", "Specific wedge with early pull."),
        ]
        for axis, score, confidence, rationale in axis_rows:
            session.add(
                OpportunityScore(
                    opportunity_id=opportunity.id,
                    axis=axis,
                    score=Decimal(score),
                    confidence=Decimal(confidence),
                    trend=TrendKind.INSUFFICIENT_DATA,
                    rationale=rationale,
                    drivers=[],
                    model_version="seed-v1",
                )
            )
        github = await session.scalar(select(Source).where(Source.key == "github"))
        assert github is not None
        claim = Claim(
            org_id=org.id,
            opportunity_id=opportunity.id,
            company_id=company.id,
            category=ClaimCategory.TRACTION,
            predicate="customer_count",
            text="The company reports 12 design partners.",
            value_num=Decimal("12"),
            value_unit="count",
            status=ClaimStatus.CORROBORATED,
            trust_score=Decimal("0.660"),
            trust_inputs={"seed": True, "source_tier": SourceTier.PRIMARY.value},
            extracted_by="seed-v1",
        )
        session.add(claim)
        await session.flush()
        session.add(
            Evidence(
                claim_id=claim.id,
                source_id=github.id,
                locator={"type": "api", "endpoint": "github:example/nullpoint", "field": "README"},
                snippet="Working with 12 design partners",
                supports=True,
                independence_group="github:nullpoint",
                observed_at=now - timedelta(days=2),
            )
        )
        draft = compose_memo(
            [
                {
                    "id": claim.id,
                    "category": claim.category.value,
                    "text": claim.text,
                    "trust_score": claim.trust_score,
                }
            ],
            DecisionKind.WATCHLIST,
            "Strong founder evidence; market diligence remains incomplete.",
        )
        session.add(
            Memo(
                org_id=org.id,
                opportunity_id=opportunity.id,
                status="ready",
                sections=draft.sections,
                recommendation=DecisionKind.WATCHLIST,
                recommendation_rationale="Strong founder evidence; market diligence remains incomplete.",
                gaps=draft.gaps,
                trust_summary={
                    status.value: int(status == ClaimStatus.CORROBORATED) for status in ClaimStatus
                },
                word_count=draft.word_count,
                cost_usd=Decimal("0"),
                model_version="seed-v1",
            )
        )
        await session.commit()
        print("Seeded demo@vcbrain.dev / Demo-password-42!")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
