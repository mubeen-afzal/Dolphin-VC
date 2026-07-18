import pytest

from tests.conftest import signup_client


@pytest.mark.integration
async def test_cross_org_opportunity_is_404(client) -> None:
    first = await signup_client(client, "first@example.com")
    second = await signup_client(client, "second@example.com")
    created = await client.post(
        "/api/v1/opportunities",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={"company_name": "Tenant One Co", "origin": "manual"},
    )
    assert created.status_code == 201, created.text
    opportunity_id = created.json()["id"]
    cross_org = await client.get(
        f"/api/v1/opportunities/{opportunity_id}",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert cross_org.status_code == 404
