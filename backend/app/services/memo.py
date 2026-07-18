from dataclasses import dataclass
from typing import Any

from app.types import ClaimCategory, DecisionKind

REQUIRED_SECTIONS = {
    "company_snapshot": {ClaimCategory.PRODUCT, ClaimCategory.MARKET},
    "investment_hypotheses": {ClaimCategory.TEAM, ClaimCategory.TRACTION, ClaimCategory.TECHNOLOGY},
    "swot": {ClaimCategory.MARKET, ClaimCategory.PRODUCT, ClaimCategory.TECHNOLOGY},
    "problem_product": {ClaimCategory.PRODUCT},
    "traction_kpis": {ClaimCategory.TRACTION, ClaimCategory.REVENUE},
}


@dataclass(frozen=True)
class MemoDraft:
    sections: list[dict[str, Any]]
    gaps: list[dict[str, str]]
    word_count: int


def compose_memo(
    claims: list[dict[str, Any]], recommendation: DecisionKind, rationale: str
) -> MemoDraft:
    sections: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for key, categories in REQUIRED_SECTIONS.items():
        relevant = [
            claim
            for claim in claims
            if claim.get("category") in {item.value for item in categories}
        ]
        if relevant:
            bullets = [
                f"- {claim['text']} [claim:{claim['id']}] (trust {float(claim['trust_score']):.2f})"
                for claim in relevant
            ]
            markdown = "\n".join(bullets)
            claim_ids = [str(claim["id"]) for claim in relevant]
            section_gaps: list[str] = []
        else:
            markdown = "Not disclosed in the available evidence."
            claim_ids = []
            section_gaps = ["No evidence-backed claims are available for this section."]
            gaps.append(
                {
                    "field": key,
                    "reason": "not_disclosed",
                    "how_to_resolve": "Request primary documentation or a founder answer.",
                }
            )
        sections.append(
            {
                "key": key,
                "title": key.replace("_", " ").title(),
                "markdown": markdown,
                "claim_ids": claim_ids,
                "gaps": section_gaps,
            }
        )
    sections.append(
        {
            "key": "recommendation",
            "title": "Recommendation",
            "markdown": f"**{recommendation.value.replace('_', ' ').title()}** — {rationale}",
            "claim_ids": [],
            "gaps": [],
        }
    )
    word_count = sum(len(section["markdown"].split()) for section in sections)
    return MemoDraft(sections=sections, gaps=gaps, word_count=word_count)
