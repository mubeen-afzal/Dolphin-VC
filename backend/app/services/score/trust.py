import math
from dataclasses import dataclass
from datetime import UTC, datetime

from app.types import ClaimCategory, ClaimStatus, SourceTier

TIER_BASE = {
    SourceTier.PRIMARY: 0.92,
    SourceTier.VERIFIED_THIRD_PARTY: 0.85,
    SourceTier.AGGREGATOR: 0.65,
    SourceTier.SELF_REPORTED: 0.40,
    SourceTier.INFERRED: 0.25,
}
HALF_LIFE = {
    ClaimCategory.TRACTION: 90,
    ClaimCategory.REVENUE: 120,
    ClaimCategory.TEAM: 365,
    ClaimCategory.MARKET: 180,
    ClaimCategory.PRODUCT: 180,
    ClaimCategory.TECHNOLOGY: 365,
    ClaimCategory.FUNDING: 540,
    ClaimCategory.LEGAL: 540,
    ClaimCategory.OTHER: 180,
}


@dataclass(frozen=True)
class TrustEvidence:
    reliability: float
    independence_group: str


@dataclass(frozen=True)
class TrustResult:
    score: float
    status: ClaimStatus
    inputs: dict[str, float | bool | int]


def compute_trust(
    *,
    tier: SourceTier,
    category: ClaimCategory,
    evidence: list[TrustEvidence],
    observed_at: datetime | None,
    extraction_confidence: float,
    contradicted: bool = False,
    independently_verified: bool = False,
    now: datetime | None = None,
) -> TrustResult:
    now = now or datetime.now(UTC)
    groups: set[str] = set()
    product = 1.0
    for item in evidence:
        independence = 1.0 if item.independence_group not in groups else 0.25
        groups.add(item.independence_group)
        product *= 1.0 - max(0.0, min(1.0, item.reliability)) * independence
    corroboration = 1.0 - product
    if observed_at is None:
        recency = 0.5
    else:
        timestamp = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
        age_days = max(0, (now - timestamp).days)
        recency = math.exp(-age_days / HALF_LIFE[category])
    contradiction_multiplier = 0.45 if contradicted else 1.0
    verified_multiplier = 1.15 if independently_verified else 1.0
    base = TIER_BASE[tier]
    score = base * (0.35 + 0.65 * corroboration) * (0.6 + 0.4 * recency)
    score *= max(0.0, min(1.0, extraction_confidence))
    score *= contradiction_multiplier * verified_multiplier
    score = round(max(0.02, min(0.99, score)), 3)
    if contradicted:
        status = ClaimStatus.CONTRADICTED
    elif score >= 0.80:
        status = ClaimStatus.VERIFIED
    elif score >= 0.55:
        status = ClaimStatus.CORROBORATED
    elif score >= 0.30:
        status = ClaimStatus.CLAIMED
    else:
        status = ClaimStatus.UNVERIFIABLE
    return TrustResult(
        score=score,
        status=status,
        inputs={
            "base": base,
            "corroboration": round(corroboration, 4),
            "independent_sources": len(groups),
            "recency": round(recency, 4),
            "extraction": extraction_confidence,
            "contradicted": contradicted,
            "independently_verified": independently_verified,
        },
    )
