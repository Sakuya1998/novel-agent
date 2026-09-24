"""Security and release-contract regression checks for the split deployment."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient


async def test_cors_allowlist_does_not_reflect_unknown_origins(api_env):
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://test") as client:
        response = await client.options(
            "/api/novels",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"


async def test_cookie_mutation_requires_csrf_and_secure_session_attributes(api_env):
    api_env.cfg.auth_enabled = True
    api_env.cfg.app_environment = "production"
    api_env.cfg.auth_cookie_secure = None
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="https://test") as client:
        registered = await client.post("/api/auth/register", json={
            "username": "security_contract_user",
            "email": "security-contract@example.com",
            "password": "security-password",
            "tenant_name": "Security Contract",
        })
        assert registered.status_code == 201
        without_csrf = await client.post("/api/novels", json={"title": "CSRF denied", "inspiration": "blocked"})
        with_csrf = await client.post(
            "/api/novels",
            headers={"X-CSRF-Token": client.cookies["novel_agent_csrf"]},
            json={"title": "CSRF allowed", "inspiration": "accepted"},
        )
    assert without_csrf.status_code == 403
    assert with_csrf.status_code == 200
    session_cookie = next(
        value for value in registered.headers.get_list("set-cookie") if value.startswith("novel_agent_session=")
    )
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie


async def test_workspace_resource_contract_is_scoped_and_auditable(api_env):
    schema = api_env.app.openapi()
    assert "/api/workspaces/{workspace_id}/{resource_kind}" in schema["paths"]
    assert "/api/audit/logs" in schema["paths"]
    assert "/api/jobs/{job_id}/events" in schema["paths"]
