import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Application, Company, Document, Job, Opportunity, Thesis
from app.errors import AppError
from app.services.object_store import ObjectStore, sniff_document_mime
from app.services.utils import normalize_name, utcnow
from app.types import ApplicationStatus, JobStatus, OpportunityOrigin, OpportunityStage


@dataclass(frozen=True)
class CreatedApplication:
    application: Application
    opportunity: Opportunity
    job: Job
    tracking_token: str | None
    replayed: bool = False


async def create_application(
    session: AsyncSession,
    settings: Settings,
    store: ObjectStore,
    *,
    org_id: uuid.UUID,
    company_name: str,
    deck_bytes: bytes | None,
    original_filename: str | None,
    website: str | None,
    contact_email: str | None,
    contact_name: str | None,
    artifacts: list[str],
    notes: str | None,
    source_channel: str,
    submitted_ip: str | None,
    uploaded_by: uuid.UUID | None,
    idempotency_key: str | None,
    public: bool = False,
) -> CreatedApplication:
    if not company_name.strip():
        raise AppError("VALIDATION_ERROR", "Company name is required.")
    if deck_bytes is None and not website:
        raise AppError(
            "VALIDATION_ERROR",
            "Deck file is required when no website is provided.",
            field_errors=[
                {"field": "deck", "code": "required", "message": "Upload a PDF or PPTX."}
            ],
        )
    if idempotency_key:
        prior = await session.scalar(
            select(Job).where(
                Job.org_id == org_id,
                Job.kind == "application.process",
                Job.idempotency_key == idempotency_key,
            )
        )
        if prior and prior.input.get("application_id"):
            application = await session.get(Application, uuid.UUID(prior.input["application_id"]))
            opportunity = await session.get(Opportunity, uuid.UUID(prior.input["opportunity_id"]))
            if application and opportunity:
                return CreatedApplication(application, opportunity, prior, None, replayed=True)

    hostname = urlsplit(website).hostname if website else None
    domain = hostname.casefold() if hostname else None
    normalized = normalize_name(company_name)
    company = None
    if domain:
        company = await session.scalar(select(Company).where(Company.domain == domain))
    if company is None:
        company = await session.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is None:
        company = Company(
            name=company_name.strip(),
            normalized_name=normalized,
            domain=domain,
            links={"website": website} if website else {},
            is_stub=True,
        )
        session.add(company)
        await session.flush()

    document = None
    if deck_bytes is not None:
        mime = sniff_document_mime(deck_bytes)
        digest = hashlib.sha256(deck_bytes).hexdigest()
        document = await session.scalar(
            select(Document).where(Document.org_id == org_id, Document.sha256 == digest)
        )
        if document is None:
            suffix = ".pdf" if mime == "application/pdf" else ".pptx"
            key, digest = await store.put(
                deck_bytes,
                bucket=settings.s3_bucket_decks,
                suffix=suffix,
            )
            document = Document(
                org_id=org_id,
                company_id=company.id,
                kind="deck",
                filename=Path(original_filename or f"deck{suffix}").name,
                mime=mime,
                size_bytes=len(deck_bytes),
                sha256=digest,
                s3_key=key,
                uploaded_by=uploaded_by,
            )
            session.add(document)
            await session.flush()

    opportunity = await session.scalar(
        select(Opportunity).where(
            Opportunity.org_id == org_id,
            Opportunity.company_id == company.id,
            Opportunity.stage != OpportunityStage.ARCHIVED,
        )
    )
    if opportunity is None:
        default_thesis = await session.scalar(
            select(Thesis).where(
                Thesis.org_id == org_id, Thesis.is_default.is_(True), Thesis.deleted_at.is_(None)
            )
        )
        now = utcnow()
        opportunity = Opportunity(
            org_id=org_id,
            company_id=company.id,
            thesis_id=default_thesis.id if default_thesis else None,
            origin=OpportunityOrigin.INBOUND,
            title=company.name,
            first_signal_at=now,
            sla_deadline_at=now + timedelta(hours=settings.decision_sla_hours),
            dedupe_key=f"{org_id}:{company.id}",
        )
        session.add(opportunity)
        await session.flush()

    tracking_token = secrets.token_urlsafe(24) if public else None
    application = Application(
        org_id=org_id,
        company_name=company_name.strip(),
        deck_document_id=document.id if document else None,
        contact_email=contact_email.casefold() if contact_email else None,
        contact_name=contact_name,
        website=website,
        extra={"artifacts": artifacts, "notes": notes},
        status=ApplicationStatus.RECEIVED,
        submitted_ip=submitted_ip,
        opportunity_id=opportunity.id,
        source_channel=source_channel,
        tracking_token_hash=hashlib.sha256(tracking_token.encode()).hexdigest()
        if tracking_token
        else None,
    )
    session.add(application)
    await session.flush()
    job = Job(
        org_id=org_id,
        kind="application.process",
        status=JobStatus.QUEUED,
        target_type="opportunity",
        target_id=opportunity.id,
        idempotency_key=idempotency_key,
        input={
            "application_id": str(application.id),
            "opportunity_id": str(opportunity.id),
            "document_id": str(document.id) if document else None,
            "public": public,
        },
    )
    session.add(job)
    await session.flush()
    return CreatedApplication(application, opportunity, job, tracking_token)
