"""Versioned API contract smoke tests."""

from httpx import ASGITransport, AsyncClient

from novel_agent.api import server


async def test_v1_metadata_declares_contract_version():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        response = await client.get("/api/v1")

    assert response.status_code == 200
    assert response.json() == {"version": "v1", "service": "novel-agent"}
    assert response.headers["X-API-Version"] == "v1"


async def test_v1_unknown_route_uses_error_envelope():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"]
    assert "message" in body


async def test_v1_auth_status_aliases_existing_auth_contract():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        response = await client.get("/api/v1/auth/status")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.headers["X-API-Version"] == "v1"
