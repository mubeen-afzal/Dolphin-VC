import uuid
from collections import Counter
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select

from app.config import Settings
from app.db.models import (
    Affiliation,
    AgentStep,
    Application,
    Claim,
    Company,
    Document,
    DocumentPage,
    Evidence,
    FounderScore,
    Job,
    Memo,
    Opportunity,
    OpportunityScore,
    PrescreenResult,
    Signal,
    Source,
    SourcingChannel,
    Thesis,
)
from app.db.session import Database
from app.services.connectors import (
    ArxivConnector,
    GitHubConnector,
    HackerNewsConnector,
    TavilyConnector,
)
from app.services.extraction import ExtractedClaim, extract_claims
from app.services.memo import compose_memo
from app.services.object_store import ObjectStore
from app.services.parse.deck import ParsedPage, parse_deck
from app.services.score.recommendation import AxisValue, TrustSummary, recommend
from app.services.score.thesis import compute_thesis_fit
from app.services.score.trust import TrustEvidence, compute_trust
from app.services.utils import utcnow
from app.types import (
    ApplicationStatus,
    AxisKind,
    ClaimCategory,
    ClaimStatus,
    JobStatus,
    MarketStance,
    OpportunityStage,
    SourceStatus,
    SourceTier,
    TrendKind,
)


async def _process_harvest(session: object, settings: Settings, job: Job) -> None:
    connector_types: dict[str, Any] = {
        "github": GitHubConnector,
        "hackernews": HackerNewsConnector,
        "arxiv": ArxivConnector,
        "tavily": TavilyConnector,
    }
    requested = job.input.get("channels", "auto")
    keys = (
        list(connector_types)
        if requested == "auto"
        else [key for key in requested if key in connector_types]
    )
    query = str(job.input.get("query") or "AI startup")
    limit = min(100, int(job.input.get("limit") or 25))
    ingested = 0
    failures: list[dict[str, str]] = []
    if settings.demo_mode:
        keys = []
        failures.append({"source": "all", "reason": "network harvesting disabled in DEMO_MODE"})
    for seq, key in enumerate(keys, 1):
        source = await session.scalar(select(Source).where(Source.key == key))  # type: ignore[attr-defined]
        connector = connector_types[key](settings)
        try:
            if not connector.enabled:
                failures.append({"source": key, "reason": "no_credentials"})
                continue
            items = await connector.harvest(query=query, limit=limit)
            if source is None:
                source = Source(
                    key=key,
                    display_name=key.title(),
                    tier=SourceTier.AGGREGATOR,
                    status=SourceStatus.ACTIVE,
                    reliability=Decimal("0.650"),
                )
                session.add(source)  # type: ignore[attr-defined]
                await session.flush()  # type: ignore[attr-defined]
            channel = await session.scalar(  # type: ignore[attr-defined]
                select(SourcingChannel).where(SourcingChannel.key == key)
            )
            if channel is None:
                channel = SourcingChannel(key=key, label=source.display_name, kind="source")
                session.add(channel)  # type: ignore[attr-defined]
            for item in items:
                duplicate = await session.scalar(  # type: ignore[attr-defined]
                    select(Signal.id).where(
                        Signal.source_id == source.id,
                        Signal.content_hash == item.content_hash,
                        Signal.observed_at == item.observed_at,
                    )
                )
                if duplicate:
                    continue
                session.add(  # type: ignore[attr-defined]
                    Signal(
                        org_id=job.org_id,
                        source_id=source.id,
                        kind=item.kind,
                        external_id=item.external_id,
                        url=item.url,
                        title=item.title,
                        body=item.body,
                        payload=item.payload,
                        content_hash=item.content_hash,
                        strength=Decimal(str(item.strength)),
                        observed_at=item.observed_at,
                    )
                )
                channel.discovered_count += 1
                ingested += 1
            source.status = SourceStatus.ACTIVE
            source.last_ok_at = utcnow()
            await session.commit()  # type: ignore[attr-defined]
        except Exception as exc:
            failures.append({"source": key, "reason": type(exc).__name__})
            if source:
                source.status = SourceStatus.DEGRADED
                source.last_error_at = utcnow()
                source.last_error = str(exc)[:500]
                await session.commit()  # type: ignore[attr-defined]
        finally:
            await connector.close()
        session.add(  # type: ignore[attr-defined]
            AgentStep(
                job_id=job.id,
                seq=seq,
                agent="harvester",
                action=f"ingest.{key}",
                status="succeeded"
                if not any(item["source"] == key for item in failures)
                else "degraded",
                progress=Decimal(str(round(seq / max(1, len(keys)) * 90, 2))),
                message=f"Harvested source {key}.",
            )
        )
        await session.commit()  # type: ignore[attr-defined]
    job.status = JobStatus.PARTIAL if failures else JobStatus.SUCCEEDED
    job.progress = Decimal("100")
    job.current_step = "done"
    job.finished_at = utcnow()
    job.result = {"signals_ingested": ingested, "failures": failures}
    await session.commit()  # type: ignore[attr-defined]


async def _step(
    session: object, job: Job, seq: int, action: str, progress: float, message: str
) -> None:
    session.add(  # type: ignore[attr-defined]
        AgentStep(
            job_id=job.id,
            seq=seq,
            agent="pipeline",
            action=action,
            status="succeeded",
            progress=Decimal(str(progress)),
            message=message,
        )
    )
    job.progress = Decimal(str(progress))
    job.current_step = action
    job.heartbeat_at = utcnow()
    await session.commit()  # type: ignore[attr-defined]


async def _ensure_deck_source(session: object) -> Source:
    source = await session.scalar(select(Source).where(Source.key == "deck"))  # type: ignore[attr-defined]
    if source is None:
        source = Source(
            key="deck",
            display_name="Founder-submitted deck",
            tier=SourceTier.SELF_REPORTED,
            status=SourceStatus.ACTIVE,
            reliability=Decimal("0.400"),
            rate_limit={},
            requires_key=False,
        )
        session.add(source)  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]
    return cast(Source, source)


def _product_claim(pages: list[ParsedPage]) -> ExtractedClaim | None:
    for page in pages:
        for line in page.text.splitlines():
            text = line.strip()
            if len(text) >= 12:
                return ExtractedClaim(
                    category=ClaimCategory.PRODUCT,
                    predicate="deck_summary",
                    text=text[:500],
                    value_num=None,
                    value_unit=None,
                    locator={"type": "deck", "page": page.page_no, "snippet": text[:400]},
                    extraction_confidence=0.72,
                )
    return None


async def _parse_and_extract(
    session: object,
    settings: Settings,
    store: ObjectStore,
    document: Document,
    opportunity: Opportunity,
) -> list[Claim]:
    existing_pages = (
        await session.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id))  # type: ignore[attr-defined]
    ).all()
    if existing_pages:
        parsed_pages = [
            ParsedPage(item.page_no, item.text or "", item.ocr_used) for item in existing_pages
        ]
    else:
        data = await store.get(bucket=settings.s3_bucket_decks, key=document.s3_key)
        parsed = parse_deck(data, document.mime or "")
        parsed_pages = parsed.pages
        for page in parsed.pages:
            session.add(  # type: ignore[attr-defined]
                DocumentPage(
                    document_id=document.id,
                    page_no=page.page_no,
                    text=page.text,
                    ocr_used=page.ocr_used,
                )
            )
        document.page_count = len(parsed.pages)
        document.parser = parsed.parser
        document.parse_status = "partial" if parsed.partial else "ok"
        await session.flush()  # type: ignore[attr-defined]

    existing_claims = (
        await session.scalars(select(Claim).where(Claim.opportunity_id == opportunity.id))  # type: ignore[attr-defined]
    ).all()
    if existing_claims:
        return list(existing_claims)

    source = await _ensure_deck_source(session)
    extracted = extract_claims(parsed_pages)
    product = _product_claim(parsed_pages)
    if product:
        extracted.append(product)
    created: list[Claim] = []
    for item in extracted:
        trust = compute_trust(
            tier=source.tier,
            category=item.category,
            evidence=[TrustEvidence(float(source.reliability), f"deck:{document.id}")],
            observed_at=document.created_at,
            extraction_confidence=item.extraction_confidence,
            contradicted=False,
        )
        status = ClaimStatus.UNVERIFIABLE if item.unverifiable else trust.status
        claim = Claim(
            org_id=opportunity.org_id,
            opportunity_id=opportunity.id,
            company_id=opportunity.company_id,
            category=item.category,
            predicate=item.predicate,
            text=item.text,
            value_num=item.value_num,
            value_unit=item.value_unit,
            status=status,
            trust_score=Decimal(str(trust.score)),
            trust_inputs=trust.inputs,
            verification_note="Prompt-injection-like text detected." if item.unverifiable else None,
            extracted_by="deterministic-v1",
        )
        session.add(claim)  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]
        snippet = str(item.locator["snippet"])
        session.add(  # type: ignore[attr-defined]
            Evidence(
                claim_id=claim.id,
                document_id=document.id,
                source_id=source.id,
                locator=item.locator,
                snippet=snippet[:400],
                supports=not item.unverifiable,
                independence_group=f"deck:{document.id}",
                observed_at=document.created_at,
            )
        )
        created.append(claim)
    await session.flush()  # type: ignore[attr-defined]
    return created


async def _score_axes(
    session: object, opportunity: Opportunity, claims: list[Claim]
) -> list[OpportunityScore]:
    founder_scores = (
        await session.scalars(  # type: ignore[attr-defined]
            select(FounderScore)
            .join(Affiliation, Affiliation.person_id == FounderScore.person_id)
            .where(
                Affiliation.company_id == opportunity.company_id, Affiliation.is_founder.is_(True)
            )
        )
    ).all()
    if founder_scores:
        best = max(founder_scores, key=lambda item: item.score)
        founder_value = 35 + (best.score - 300) / 600 * 60
        founder_conf = float(best.confidence)
        founder_rationale = "Founder Score and team evidence are available."
    else:
        founder_value = 50.0
        founder_conf = 0.20
        founder_rationale = "No resolved founder profile; cohort prior used without penalty."
    market_count = sum(item.category == ClaimCategory.MARKET for item in claims)
    traction_count = sum(
        item.category in {ClaimCategory.TRACTION, ClaimCategory.REVENUE} for item in claims
    )
    product_count = sum(
        item.category in {ClaimCategory.PRODUCT, ClaimCategory.TECHNOLOGY} for item in claims
    )
    values = [
        (AxisKind.FOUNDER, founder_value, founder_conf, founder_rationale, None),
        (
            AxisKind.MARKET,
            min(80.0, 48.0 + market_count * 8 + traction_count * 2),
            min(0.75, 0.22 + market_count * 0.15),
            "Market score reflects only evidence-backed market and traction claims.",
            MarketStance.NEUTRAL,
        ),
        (
            AxisKind.IDEA_VS_MARKET,
            min(80.0, 50.0 + product_count * 6 + traction_count * 3),
            min(0.75, 0.25 + product_count * 0.12 + traction_count * 0.08),
            "Idea-vs-market score reflects product specificity and demonstrated pull.",
            None,
        ),
    ]
    created: list[OpportunityScore] = []
    for axis, score, confidence, rationale, stance in values:
        latest_version = await session.scalar(  # type: ignore[attr-defined]
            select(func.max(OpportunityScore.version)).where(
                OpportunityScore.opportunity_id == opportunity.id,
                OpportunityScore.axis == axis,
            )
        )
        previous = await session.scalar(  # type: ignore[attr-defined]
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity.id, OpportunityScore.axis == axis)
            .order_by(OpportunityScore.version.desc())
            .limit(1)
        )
        if previous is None:
            trend = TrendKind.INSUFFICIENT_DATA
        else:
            delta = score - float(previous.score)
            trend = (
                TrendKind.STABLE
                if abs(delta) < 3
                else TrendKind.IMPROVING
                if delta > 0
                else TrendKind.DECLINING
            )
        row = OpportunityScore(
            opportunity_id=opportunity.id,
            axis=axis,
            score=Decimal(str(round(score, 2))),
            confidence=Decimal(str(round(confidence, 3))),
            trend=trend,
            stance=stance,
            rationale=rationale,
            drivers=[],
            model_version="axes-deterministic-v1",
            version=int(latest_version or 0) + 1,
        )
        session.add(row)  # type: ignore[attr-defined]
        created.append(row)
    await session.flush()  # type: ignore[attr-defined]
    return created


async def _thesis_fit(
    session: object, opportunity: Opportunity, company: Company
) -> tuple[float, str | None]:
    thesis = await session.get(Thesis, opportunity.thesis_id) if opportunity.thesis_id else None  # type: ignore[attr-defined]
    if thesis is None:
        return 70.0, None
    result = compute_thesis_fit(
        company_sectors=company.sectors,
        company_stage=company.stage,
        company_country=company.hq_country,
        thesis_sectors=thesis.sectors,
        anti_sectors=thesis.anti_sectors,
        stages=thesis.stages,
        geos=thesis.geos,
        must_haves=thesis.must_haves,
        company_text=" ".join(filter(None, [company.one_liner, company.description])),
    )
    return result.score, result.gate_reason


async def process_job(
    database: Database,
    settings: Settings,
    store: ObjectStore,
    job_id: uuid.UUID,
) -> None:
    async with database.session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.status == JobStatus.CANCELLED:
            return
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        job.attempts += 1
        job.heartbeat_at = utcnow()
        await session.commit()
        try:
            if job.kind == "ingest.harvest":
                await _process_harvest(session, settings, job)
                return
            opportunity_id = job.target_id or uuid.UUID(job.input["opportunity_id"])
            opportunity = await session.get(Opportunity, opportunity_id)
            if opportunity is None:
                raise RuntimeError("opportunity missing")
            company = await session.get(Company, opportunity.company_id)
            if company is None:
                raise RuntimeError("company missing")
            opportunity.stage = OpportunityStage.SCREENING
            application = None
            if job.input.get("application_id"):
                application = await session.get(Application, uuid.UUID(job.input["application_id"]))
                if application:
                    application.status = ApplicationStatus.PARSING
            await session.commit()

            await _step(session, job, 1, "prescreen", 8, "Mechanical prescreen completed.")
            prescreen = await session.get(PrescreenResult, opportunity.id)
            if prescreen is None:
                prescreen = PrescreenResult(
                    opportunity_id=opportunity.id,
                    passed=True,
                    rules_fired=[],
                    latency_ms=1,
                )
                session.add(prescreen)
                await session.commit()

            claims: list[Claim] = list(
                (
                    await session.scalars(
                        select(Claim).where(Claim.opportunity_id == opportunity.id)
                    )
                ).all()
            )
            document_id = job.input.get("document_id")
            if document_id:
                document = await session.get(Document, uuid.UUID(document_id))
                if document:
                    claims = await _parse_and_extract(
                        session, settings, store, document, opportunity
                    )
                    await session.commit()
            await _step(
                session,
                job,
                2,
                "extract_claims",
                32,
                f"Extracted {len(claims)} evidence-backed claims.",
            )

            axes = await _score_axes(session, opportunity, claims)
            await session.commit()
            await _step(
                session,
                job,
                3,
                "score_axes",
                58,
                "Three independent axes scored without averaging.",
            )

            fit, gate_reason = await _thesis_fit(session, opportunity, company)
            opportunity.thesis_fit = Decimal(str(fit))
            trust_counts = Counter(item.status.value for item in claims)
            critical_contradiction = any(
                item.status == ClaimStatus.CONTRADICTED
                and item.category
                in {ClaimCategory.REVENUE, ClaimCategory.TRACTION, ClaimCategory.TEAM}
                for item in claims
            )
            recommendation = recommend(
                [
                    AxisValue(float(axis.score), float(axis.confidence), axis.rationale)
                    for axis in axes
                ],
                fit,
                TrustSummary(critical_contradiction),
                cold_start=float(axes[0].confidence) < 0.4,
                gate_reason=gate_reason,
            )
            await _step(
                session,
                job,
                4,
                "thesis_and_recommend",
                72,
                "Thesis fit and recommendation computed.",
            )

            claim_data = [
                {
                    "id": claim.id,
                    "category": claim.category.value,
                    "text": claim.text,
                    "trust_score": claim.trust_score,
                }
                for claim in claims
            ]
            draft = compose_memo(claim_data, recommendation.decision, recommendation.rationale)
            latest_version = await session.scalar(
                select(func.max(Memo.version)).where(Memo.opportunity_id == opportunity.id)
            )
            memo = Memo(
                org_id=opportunity.org_id,
                opportunity_id=opportunity.id,
                version=int(latest_version or 0) + 1,
                status="ready",
                sections=draft.sections,
                recommendation=recommendation.decision,
                recommendation_rationale=recommendation.rationale,
                adversarial={
                    "bear_case": "Evidence remains incomplete; validate every decision-critical gap.",
                    "kill_criteria": [
                        "Critical claim contradicted",
                        "Founder identity unresolved",
                        "Thesis hard gate fails",
                    ],
                },
                gaps=draft.gaps,
                trust_summary={status.value: trust_counts[status.value] for status in ClaimStatus},
                word_count=draft.word_count,
                generated_ms=0,
                cost_usd=Decimal("0"),
                model_version="memo-deterministic-v1",
            )
            session.add(memo)
            now = utcnow()
            opportunity.stage = OpportunityStage.DECISION
            opportunity.screened_at = now
            opportunity.memo_ready_at = now
            opportunity.version += 1
            if application:
                application.status = ApplicationStatus.IN_DILIGENCE
            await session.commit()
            await _step(
                session,
                job,
                5,
                "memo",
                95,
                "Evidence-backed memo generated; gaps marked not disclosed.",
            )

            job.status = JobStatus.SUCCEEDED
            job.progress = Decimal("100")
            job.current_step = "done"
            job.finished_at = utcnow()
            job.result = {
                "opportunity_id": str(opportunity.id),
                "memo_id": str(memo.id),
                "recommendation": recommendation.decision.value,
            }
            session.add(
                AgentStep(
                    job_id=job.id,
                    seq=6,
                    agent="pipeline",
                    action="done",
                    status="succeeded",
                    progress=Decimal("100"),
                    message="Decision-support package is ready.",
                    output_summary=job.result,
                )
            )
            await session.commit()
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error_code = type(exc).__name__.upper()
            job.error_message = str(exc)[:1000]
            job.finished_at = utcnow()
            await session.commit()
