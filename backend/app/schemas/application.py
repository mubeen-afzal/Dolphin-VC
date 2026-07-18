import uuid
from datetime import datetime

from app.schemas.common import APIModel
from app.types import ApplicationStatus


class ApplicationAccepted(APIModel):
    application_id: uuid.UUID
    opportunity_id: uuid.UUID
    job_id: uuid.UUID
    estimated_seconds: int


class PublicApplicationAccepted(APIModel):
    application_id: uuid.UUID
    tracking_token: str


class ApplicationOut(APIModel):
    id: uuid.UUID
    org_id: uuid.UUID
    company_name: str
    contact_email: str | None
    contact_name: str | None
    website: str | None
    status: ApplicationStatus
    opportunity_id: uuid.UUID | None
    source_channel: str | None
    received_at: datetime
    created_at: datetime
    updated_at: datetime


class PublicApplicationStatus(APIModel):
    status: ApplicationStatus
    stage: str | None
    submitted_at: datetime
    decided_at: datetime | None
    hours_remaining: float
    message: str
