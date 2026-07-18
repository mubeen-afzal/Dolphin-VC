from pydantic import Field

from app.schemas.common import StrictRequest


class HarvestRequest(StrictRequest):
    channels: str | list[str] = "auto"
    limit: int = Field(default=25, ge=1, le=100)
    query: str = Field(default="AI startup", min_length=2, max_length=200)


class RejectOutreachRequest(StrictRequest):
    reason: str = Field(min_length=3, max_length=1000)
