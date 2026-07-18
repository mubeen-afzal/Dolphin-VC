from app.config import Settings
from app.services.connectors.github import GitHubConnector
from app.types import SignalKind


def test_github_normalize_is_pure() -> None:
    connector = GitHubConnector(Settings())
    raw = {
        "id": 42,
        "full_name": "founder/project",
        "html_url": "https://github.com/founder/project",
        "description": "AI infrastructure",
        "pushed_at": "2026-07-18T09:00:00Z",
        "stargazers_count": 120,
        "forks_count": 10,
        "language": "Python",
        "topics": ["ai"],
        "owner": {"login": "founder"},
    }
    first = connector.normalize(raw)
    second = connector.normalize(raw)
    assert first == second
    assert first.kind == SignalKind.REPO_ACTIVITY
    assert first.content_hash == second.content_hash
