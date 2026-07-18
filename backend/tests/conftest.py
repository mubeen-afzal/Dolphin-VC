import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.services.seeding import seed_reference_data


@pytest.fixture
async def app(tmp_path: Path):
    external_database = os.getenv("TEST_DATABASE_URL")
    settings = Settings(
        env="test",
        database_url=external_database or f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
        redis_url="redis://localhost:6399/15",
        storage_backend="local",
        local_storage_path=tmp_path / "objects",
        auto_create_schema=True,
        queue_eager=True,
        demo_mode=True,
        secret_key="test-secret-key-that-is-longer-than-thirty-two-bytes",
        frontend_origins="http://testserver",
    )
    application = create_app(settings)
    async with LifespanManager(application):
        if external_database:
            await application.state.database.drop_schema()
            await application.state.database.create_schema()
            async with application.state.database.session_factory() as session:
                await seed_reference_data(session, settings)
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as http_client:
        yield http_client


async def signup_client(client: AsyncClient, email: str = "owner@example.com") -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "A-strong-test-password-42!",
            "full_name": "Test Owner",
            "org_name": f"Fund {email.split('@')[0]}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
