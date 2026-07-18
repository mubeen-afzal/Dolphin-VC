import re
from dataclasses import dataclass
from decimal import Decimal

from app.services.parse.deck import ParsedPage
from app.services.security import looks_like_prompt_injection
from app.types import ClaimCategory


@dataclass(frozen=True)
class ExtractedClaim:
    category: ClaimCategory
    predicate: str
    text: str
    value_num: Decimal | None
    value_unit: str | None
    locator: dict[str, object]
    extraction_confidence: float
    unverifiable: bool = False


PATTERNS: list[tuple[ClaimCategory, str, re.Pattern[str], str | None]] = [
    (
        ClaimCategory.REVENUE,
        "arr",
        re.compile(r"\bARR\b[^\n]{0,30}?([$€£]?\s?\d+(?:[.,]\d+)?\s?[kKmM]?)", re.I),
        "currency",
    ),
    (
        ClaimCategory.TRACTION,
        "customer_count",
        re.compile(r"\b(\d[\d,]*)\s+(?:paying\s+)?customers?\b", re.I),
        "count",
    ),
    (
        ClaimCategory.MARKET,
        "tam",
        re.compile(r"\bTAM\b[^\n]{0,30}?([$€£]?\s?\d+(?:[.,]\d+)?\s?[bBmM]?)", re.I),
        "currency",
    ),
    (
        ClaimCategory.TRACTION,
        "growth_rate_pct",
        re.compile(r"\b(\d+(?:\.\d+)?)\s?%\s+(?:MoM|month[- ]over[- ]month|growth)\b", re.I),
        "percent",
    ),
]


def _parse_compact_number(value: str) -> Decimal | None:
    cleaned = value.replace("$", "").replace("€", "").replace("£", "").replace(",", "").strip()
    multiplier = Decimal(1)
    if cleaned and cleaned[-1].casefold() == "k":
        multiplier = Decimal(1_000)
        cleaned = cleaned[:-1]
    elif cleaned and cleaned[-1].casefold() == "m":
        multiplier = Decimal(1_000_000)
        cleaned = cleaned[:-1]
    elif cleaned and cleaned[-1].casefold() == "b":
        multiplier = Decimal(1_000_000_000)
        cleaned = cleaned[:-1]
    try:
        return Decimal(cleaned) * multiplier
    except Exception:
        return None


def extract_claims(pages: list[ParsedPage]) -> list[ExtractedClaim]:
    claims: list[ExtractedClaim] = []
    for page in pages:
        for line in (item.strip() for item in page.text.splitlines() if item.strip()):
            injected = looks_like_prompt_injection(line)
            for category, predicate, pattern, unit_type in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                snippet = match.group(0)
                # Mechanical provenance gate: the literal snippet must occur in source text.
                if snippet not in line:
                    continue
                raw_value = match.group(1)
                value = _parse_compact_number(raw_value)
                unit = None
                if unit_type == "currency":
                    unit = "EUR" if "€" in raw_value else "GBP" if "£" in raw_value else "USD"
                elif unit_type == "count":
                    unit = "count"
                elif unit_type == "percent":
                    unit = "percent"
                claims.append(
                    ExtractedClaim(
                        category=category,
                        predicate=predicate,
                        text=line[:500],
                        value_num=value,
                        value_unit=unit,
                        locator={"type": "deck", "page": page.page_no, "snippet": snippet},
                        extraction_confidence=0.30 if injected else 0.82,
                        unverifiable=injected,
                    )
                )
    return claims
