import pytest

from tests.conftest import signup_client


@pytest.mark.integration
async def test_signup_login_me_and_refresh_rotation(client) -> None:
    created = await signup_client(client)
    access = created["access_token"]
    first_refresh = created["refresh_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "owner"

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert refreshed.status_code == 200
    second_refresh = refreshed.json()["refresh_token"]
    assert second_refresh != first_refresh

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "TOKEN_REVOKED"

    family_revoked = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second_refresh}
    )
    assert family_revoked.status_code == 401


@pytest.mark.integration
async def test_validation_errors_use_frozen_error_shape(client) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "not-email", "password": "x"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"]
    assert error["field_errors"]
