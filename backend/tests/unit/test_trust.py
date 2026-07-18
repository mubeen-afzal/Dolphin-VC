from datetime import UTC, datetime

from app.services.score.trust import TrustEvidence, compute_trust
from app.types import ClaimCategory, ClaimStatus, SourceTier


def test_trust_is_per_claim_and_explainable() -> None:
    result = compute_trust(
        tier=SourceTier.PRIMARY,
        category=ClaimCategory.REVENUE,
        evidence=[
            TrustEvidence(0.92, "registry"),
            TrustEvidence(0.85, "customer_reference"),
        ],
        observed_at=datetime.now(UTC),
        extraction_confidence=0.95,
        independently_verified=True,
    )
    assert result.score >= 0.8
    assert result.status == ClaimStatus.VERIFIED
    assert result.inputs["independent_sources"] == 2


def test_contradiction_is_never_hidden() -> None:
    result = compute_trust(
        tier=SourceTier.PRIMARY,
        category=ClaimCategory.TRACTION,
        evidence=[TrustEvidence(0.95, "primary")],
        observed_at=datetime.now(UTC),
        extraction_confidence=1,
        contradicted=True,
    )
    assert result.status == ClaimStatus.CONTRADICTED
    assert result.inputs["contradicted"] is True
