import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

from app.errors import AppError

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def address_is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def validate_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppError("VALIDATION_ERROR", "Only absolute HTTP(S) URLs are accepted.")
    if parsed.username or parsed.password:
        raise AppError("VALIDATION_ERROR", "URLs containing credentials are not accepted.")
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname in BLOCKED_HOSTNAMES:
        raise AppError("VALIDATION_ERROR", "The URL points to a blocked host.")

    def resolve() -> list[Any]:
        return socket.getaddrinfo(
            hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )

    try:
        records = await asyncio.wait_for(asyncio.to_thread(resolve), timeout=3)
    except (TimeoutError, socket.gaierror) as exc:
        raise AppError("VALIDATION_ERROR", "The URL host cannot be resolved.") from exc
    addresses = {record[4][0] for record in records}
    if not addresses or any(not address_is_public(item) for item in addresses):
        raise AppError("VALIDATION_ERROR", "The URL resolves to a private or unsafe network.")
    return url


def looks_like_prompt_injection(text: str) -> bool:
    patterns = (
        "ignore previous",
        "ignore all prior",
        "system prompt",
        "you are now",
        "override your instructions",
    )
    folded = text.casefold()
    return any(pattern in folded for pattern in patterns)
