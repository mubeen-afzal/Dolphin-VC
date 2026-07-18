import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Query, Request, Response, UploadFile
from sqlalchemy import select

from app.db.models import Application, Opportunity, Org
from app.deps import DBSession, ReadPrincipal, ScreenPrincipal
from app.errors import AppError, NotFoundError
from app.schemas.application import (
    ApplicationAccepted,
    ApplicationOut,
    PublicApplicationAccepted,
    PublicApplicationStatus,
)
from app.schemas.common import CursorPage
from app.services.applications import create_application
from app.services.jobs import dispatch_job
from app.services.object_store import read_limited_upload
from app.services.security import validate_public_url
from app.services.utils import aware, utcnow
from app.types import ApplicationStatus

router = APIRouter(tags=["applications"])


async def _validate_urls(website: str | None, artifacts: list[str]) -> None:
    if website:
        await validate_public_url(website)
    for artifact in artifacts[:10]:
        await validate_public_url(artifact)


@router.post("/applications", response_model=ApplicationAccepted, status_code=202)
async def submit_application(
    request: Request,
    response: Response,
    principal: ScreenPrincipal,
    session: DBSession,
    company_name: Annotated[str, Form(min_length=1, max_length=200)],
    deck: Annotated[UploadFile | None, File()] = None,
    website: Annotated[str | None, Form()] = None,
    contact_email: Annotated[str | None, Form()] = None,
    contact_name: Annotated[str | None, Form()] = None,
    artifacts: Annotated[list[str] | None, Form()] = None,
    notes: Annotated[str | None, Form(max_length=5000)] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApplicationAccepted:
    if not idempotency_key:
        raise AppError("VALIDATION_ERROR", "Idempotency-Key header is required.")
    artifact_list = artifacts or []
    await _validate_urls(website, artifact_list)
    data = (
        await read_limited_upload(deck, request.app.state.settings.max_upload_mb) if deck else None
    )
    result = await create_application(
        session,
        request.app.state.settings,
        request.app.state.object_store,
        org_id=principal.org_id,
        company_name=company_name,
        deck_bytes=data,
        original_filename=deck.filename if deck else None,
        website=website,
        contact_email=contact_email,
        contact_name=contact_name,
        artifacts=artifact_list,
        notes=notes,
        source_channel="web_form",
        submitted_ip=request.client.host if request.client else None,
        uploaded_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    if result.replayed:
        response.headers["Idempotent-Replay"] = "true"
    else:
        await dispatch_job(
            database=request.app.state.database,
            settings=request.app.state.settings,
            store=request.app.state.object_store,
            job_id=result.job.id,
        )
    return ApplicationAccepted(
        application_id=result.application.id,
        opportunity_id=result.opportunity.id,
        job_id=result.job.id,
        estimated_seconds=90,
    )


@router.get("/applications", response_model=CursorPage[ApplicationOut])
async def list_applications(
    principal: ReadPrincipal,
    session: DBSession,
    status: ApplicationStatus | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> CursorPage[ApplicationOut]:
    query = select(Application).where(
        Application.org_id == principal.org_id,
        Application.deleted_at.is_(None),
    )
    if status:
        query = query.where(Application.status == status)
    rows = (
        await session.scalars(query.order_by(Application.received_at.desc()).limit(limit))
    ).all()
    return CursorPage(
        items=[ApplicationOut.model_validate(row) for row in rows],
        total_estimate=len(rows),
    )


@router.get("/applications/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID,
    principal: ReadPrincipal,
    session: DBSession,
) -> ApplicationOut:
    row = await session.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.org_id == principal.org_id,
            Application.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFoundError("Application")
    return ApplicationOut.model_validate(row)


@router.post("/applications/{application_id}/request-info")
async def request_application_info(
    application_id: uuid.UUID,
    principal: ScreenPrincipal,
    session: DBSession,
) -> dict[str, list[str]]:
    row = await session.scalar(
        select(Application).where(
            Application.id == application_id, Application.org_id == principal.org_id
        )
    )
    if row is None:
        raise NotFoundError("Application")
    row.status = ApplicationStatus.NEEDS_INFO
    await session.commit()
    return {
        "questions": [
            "What evidence best demonstrates that the problem is urgent?",
            "What have you shipped, and what changed after users saw it?",
            "Which decision-critical metrics can you substantiate with primary evidence?",
        ]
    }


@router.delete("/applications/{application_id}", status_code=204)
async def delete_application(
    application_id: uuid.UUID,
    principal: ScreenPrincipal,
    session: DBSession,
) -> Response:
    row = await session.scalar(
        select(Application).where(
            Application.id == application_id, Application.org_id == principal.org_id
        )
    )
    if row is None:
        raise NotFoundError("Application")
    row.deleted_at = utcnow()
    await session.commit()
    return Response(status_code=204)


@router.post("/public/apply", response_model=PublicApplicationAccepted, status_code=202)
async def public_apply(
    request: Request,
    org_slug: Annotated[str, Query(min_length=2, max_length=100)],
    session: DBSession,
    company_name: Annotated[str, Form(min_length=1, max_length=200)],
    deck: Annotated[UploadFile | None, File()] = None,
    website: Annotated[str | None, Form()] = None,
    contact_email: Annotated[str | None, Form()] = None,
    contact_name: Annotated[str | None, Form()] = None,
    artifacts: Annotated[list[str] | None, Form()] = None,
    notes: Annotated[str | None, Form(max_length=5000)] = None,
) -> PublicApplicationAccepted:
    org = await session.scalar(select(Org).where(Org.slug == org_slug))
    if org is None:
        raise NotFoundError("Fund")
    artifact_list = artifacts or []
    await _validate_urls(website, artifact_list)
    data = (
        await read_limited_upload(deck, request.app.state.settings.max_upload_mb) if deck else None
    )
    result = await create_application(
        session,
        request.app.state.settings,
        request.app.state.object_store,
        org_id=org.id,
        company_name=company_name,
        deck_bytes=data,
        original_filename=deck.filename if deck else None,
        website=website,
        contact_email=contact_email,
        contact_name=contact_name,
        artifacts=artifact_list,
        notes=notes,
        source_channel="public_form",
        submitted_ip=request.client.host if request.client else None,
        uploaded_by=None,
        idempotency_key=None,
        public=True,
    )
    await session.commit()
    await dispatch_job(
        database=request.app.state.database,
        settings=request.app.state.settings,
        store=request.app.state.object_store,
        job_id=result.job.id,
    )
    assert result.tracking_token is not None
    return PublicApplicationAccepted(
        application_id=result.application.id,
        tracking_token=result.tracking_token,
    )


@router.get("/public/apply/{tracking_token}", response_model=PublicApplicationStatus)
async def public_application_status(
    tracking_token: str,
    request: Request,
    session: DBSession,
) -> PublicApplicationStatus:
    token_hash = hashlib.sha256(tracking_token.encode()).hexdigest()
    application = await session.scalar(
        select(Application).where(Application.tracking_token_hash == token_hash)
    )
    if application is None:
        raise NotFoundError("Application")
    opportunity = (
        await session.get(Opportunity, application.opportunity_id)
        if application.opportunity_id
        else None
    )
    deadline = aware(opportunity.sla_deadline_at) if opportunity else aware(application.received_at)
    hours = (deadline - utcnow()).total_seconds() / 3600
    return PublicApplicationStatus(
        status=application.status,
        stage=opportunity.stage.value if opportunity else None,
        submitted_at=application.received_at,
        decided_at=opportunity.decided_at if opportunity else None,
        hours_remaining=round(max(0, hours), 2),
        message="Your application is being assessed against evidence, not network access.",
    )
