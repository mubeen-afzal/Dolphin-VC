from datetime import UTC, datetime
from typing import Any

from app.services.connectors.base import Connector, IdentityHint, NormalizedSignal
from app.types import SignalKind


class GitHubConnector(Connector):
    key = "github"
    requires_key = False

    @property
    def enabled(self) -> bool:
        return True

    def normalize(self, raw: dict[str, Any]) -> NormalizedSignal:
        owner = raw.get("owner") or {}
        pushed_at = raw.get("pushed_at") or raw.get("updated_at")
        observed = (
            datetime.fromisoformat(str(pushed_at).replace("Z", "+00:00"))
            if pushed_at
            else datetime.now(UTC)
        )
        return NormalizedSignal(
            kind=SignalKind.REPO_ACTIVITY,
            external_id=str(raw.get("id")) if raw.get("id") is not None else None,
            url=raw.get("html_url"),
            title=raw.get("full_name") or raw.get("name"),
            body=raw.get("description"),
            payload={
                "stars": int(raw.get("stargazers_count") or 0),
                "forks": int(raw.get("forks_count") or 0),
                "language": raw.get("language"),
                "topics": raw.get("topics") or [],
                "owner": owner.get("login"),
            },
            observed_at=observed,
            strength=min(1.0, 0.25 + int(raw.get("stargazers_count") or 0) / 5000),
            identities=[IdentityHint("github", owner["login"])] if owner.get("login") else [],
        )

    async def harvest(self, *, query: str, limit: int = 25) -> list[NormalizedSignal]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        payload = await self.get_json(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "updated", "per_page": min(limit, 100)},
            headers=headers,
        )
        return [self.normalize(item) for item in payload.get("items", [])]
