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


async def test_legacy_api_exposes_v1_successor_header():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        response = await client.get("/api/auth/status")

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/v1/auth/status>; rel="successor-version"'


async def test_v1_novel_list_uses_cursor_pagination(monkeypatch):
    novels = [{"id": f"novel_{index}"} for index in range(3)]
    monkeypatch.setattr(server.store, "list_novels", lambda: novels)
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        first = await client.get("/api/v1/novels?limit=2")
        second = await client.get(
            "/api/v1/novels",
            params={"limit": 2, "cursor": first.json()["next_cursor"]},
        )

    assert first.status_code == 200
    assert first.json()["items"] == novels[:2]
    assert first.json()["has_more"] is True
    assert second.json()["items"] == novels[2:]
    assert second.json()["has_more"] is False


async def test_v1_create_novel_replays_idempotent_request(monkeypatch):
    calls = []

    def create_novel(*args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "novel_once", "title": "幂等作品"}

    monkeypatch.setattr(server.store, "create_novel", create_novel)
    payload = {"title": "幂等作品", "inspiration": "同一个请求"}
    headers = {"Idempotency-Key": "create-key"}
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        first = await client.post("/api/v1/novels", json=payload, headers=headers)
        replay = await client.post("/api/v1/novels", json=payload, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert len(calls) == 1


async def test_v1_create_novel_rejects_reused_key_with_different_payload(monkeypatch):
    monkeypatch.setattr(server.store, "create_novel", lambda *args, **kwargs: {"id": "novel_once"})
    headers = {"Idempotency-Key": "conflicting-key"}
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        await client.post("/api/v1/novels", json={"title": "作品一", "inspiration": "灵感"}, headers=headers)
        response = await client.post(
            "/api/v1/novels",
            json={"title": "作品二", "inspiration": "另一份灵感"},
            headers=headers,
        )

    assert response.status_code == 409
    assert response.json()["code"] == "request_failed"


async def test_v1_novel_etag_rejects_stale_if_match(monkeypatch):
    novel = {"id": "novel_etag", "creative_brief_version": 3, "creative_brief": {}}
    monkeypatch.setattr(server.store, "get_novel", lambda novel_id: novel)
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        response = await client.get("/api/v1/novels/novel_etag")
        update = await client.put(
            "/api/v1/novels/novel_etag/creative-brief",
            headers={"If-Match": '"novel-novel_etag-v2"'},
            json={"creative_brief": {}},
        )

    assert response.headers["ETag"] == '"novel-novel_etag-v3"'
    assert update.status_code == 412
    assert update.json()["code"] == "request_failed"


async def test_v1_run_job_replays_idempotent_request(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_validate_model_runtime", lambda: None)
    monkeypatch.setattr(server, "_run_job_worker_id", lambda: "worker-test")
    monkeypatch.setattr(server, "_run_job_lease_seconds", lambda: 60)
    async def prepare_run_job(novel_id):
        return object()

    monkeypatch.setattr(server, "_prepare_run_job", prepare_run_job)
    monkeypatch.setattr(server, "_schedule_run_job", lambda job, payload: None)

    def create_run_job(*args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "job_once", "novel_id": "novel_job", "status": "queued"}

    monkeypatch.setattr(server.store, "create_run_job", create_run_job)
    headers = {"Idempotency-Key": "run-key-contract"}
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        first = await client.post("/api/v1/novels/novel_job/jobs/run", headers=headers)
        replay = await client.post("/api/v1/novels/novel_job/jobs/run", headers=headers)

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert len(calls) == 1
