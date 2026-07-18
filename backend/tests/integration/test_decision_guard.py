import pytest

from tests.conftest import signup_client


@pytest.mark.integration
async def test_pass_decision_cites_non_absence_reason(client) -> None:
    auth = await signup_client(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    created = await client.post(
        "/api/v1/opportunities",
        headers=headers,
        json={"company_name": "No Evidence Yet", "origin": "manual"},
    )
    opportunity_id = created.json()["id"]
    response = await client.post(
        f"/api/v1/opportunities/{opportunity_id}/decide",
        headers={**headers, "Idempotency-Key": "pass-without-evidence"},
        json={"decision": "pass", "rationale": "There is no information available yet."},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "COLD_START_INSUFFICIENT_EVIDENCE"
