import base64
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_like = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_like.casefold()).strip()


def slugify(value: str) -> str:
    return normalize_name(value).replace(" ", "-")[:80] or "organization"


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}
    ]
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    return urlunsplit(
        (parts.scheme.lower(), host + port, parts.path.rstrip("/"), urlencode(query), "")
    )


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def encode_cursor(sort_value: datetime, row_id: object) -> str:
    raw = f"{aware(sort_value).isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        timestamp, row_id = decoded.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), row_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid cursor") from exc
