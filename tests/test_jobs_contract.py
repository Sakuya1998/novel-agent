from httpx import ASGITransport, AsyncClient

from novel_agent.api import server


async def test_v1_job_events_have_resumable_envelope(api_env, fake_llm):
    from unittest.mock import patch

    async def no_checkpoint_update(*args, **kwargs):
        return None

    with patch("novel_agent.api.server._validate_model_runtime", lambda: None), patch(
        "novel_agent.api.server._graph", return_value=_event_graph()
    ), patch("novel_agent.api.server._ensure_checkpoint_creative_brief", no_checkpoint_update), patch(
        "novel_agent.api.server._prepare_run_job", new=_prepare_empty_run
    ), patch("novel_agent.api.server._run_job_worker_id", return_value="worker-test"):
        async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://test") as client:
            novel = (await client.post("/api/v1/novels", json={
                "title": "契约事件", "inspiration": "用于验证序号", "total_chapters": 1,
            })).json()
            started = await client.post(f"/api/v1/novels/{novel['id']}/jobs/run")
            assert started.status_code == 202, started.text
            job_id = started.json()["id"]
            result = None
            for _ in range(200):
                result = (await client.get(
                    f"/api/v1/jobs/{job_id}/events", params={"limit": 2}
                )).json()
                if result["job"]["status"] in {
                    "waiting_review", "completed", "failed", "cancelled", "interrupted"
                }:
                    break
            first_page = result
            next_sequence = first_page["next_after_sequence"]
            second_page = (await client.get(
                f"/api/v1/jobs/{job_id}/events",
                params={"after_sequence": next_sequence, "limit": 100},
            )).json()

    assert first_page["events"]
    assert all(set(event) == {"job_id", "sequence", "type", "payload", "created_at"}
               for event in first_page["events"])
    assert [event["sequence"] for event in first_page["events"]] == sorted(
        event["sequence"] for event in first_page["events"]
    )
    assert all(event["sequence"] > next_sequence for event in second_page["events"])
    assert all(event["job_id"] == job_id for event in second_page["events"])


async def test_v1_job_access_is_workspace_scoped(api_env):
    api_env.cfg.auth_enabled = True
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://test") as client:
        alice = (await client.post("/api/auth/register", json={
            "username": "jobs_alice", "password": "alice-password", "tenant_name": "Alice",
        })).json()
        bob = (await client.post("/api/auth/register", json={
            "username": "jobs_bob", "password": "bob-password", "tenant_name": "Bob",
        })).json()
        bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}
        novel = api_env.store.create_novel(
            "private-novel", "私有任务", tenant_id=alice["user"]["tenant_id"],
            created_by=alice["user"]["id"],
        )
        job = api_env.store.create_run_job("scoped-job", novel["id"], "run", {})
        hidden_job = await client.get(f"/api/v1/jobs/{job['id']}", headers=bob_headers)
        hidden_events = await client.get(f"/api/v1/jobs/{job['id']}/events", headers=bob_headers)
        hidden_cancel = await client.post(
            f"/api/v1/jobs/{job['id']}/cancel",
            headers={**bob_headers, "Cookie": "novel_agent_csrf=bad"},
        )

    assert hidden_job.status_code == hidden_events.status_code == hidden_cancel.status_code == 404


async def test_v1_candidate_generation_idempotency_key_replays_job(api_env, monkeypatch):
    class Snapshot:
        next = ("human_review",)
        values = {"current_draft": {"chapter_number": 1, "content": "正文"}}

    calls = []
    monkeypatch.setattr(server, "_validate_model_runtime", lambda: None)
    monkeypatch.setattr(server, "_ensure_checkpoint_creative_brief", lambda *args: _awaitable(Snapshot()))
    monkeypatch.setattr(server, "chapter_candidate_source_hash", lambda values: "source")
    monkeypatch.setattr(server, "_schedule_candidate_job", lambda *args, **kwargs: None)

    def create_job(*args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "candidate-job", "novel_id": args[1], "status": "queued"}

    monkeypatch.setattr(api_env.store, "create_run_job", create_job)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://test") as client:
        novel = (await client.post("/api/v1/novels", json={
            "title": "候选幂等", "inspiration": "正文",
        })).json()
        monkeypatch.setattr(api_env.store, "get_novel", lambda novel_id: {
            **novel, "tenant_id": "tenant_local", "creative_brief": {},
        })
        headers = {"Idempotency-Key": "candidate-key"}
        first = await client.post(
            f"/api/v1/novels/{novel['id']}/jobs/candidates",
            headers=headers,
            json={"count": 2, "instruction": "增加悬念"},
        )
        replay = await client.post(
            f"/api/v1/novels/{novel['id']}/jobs/candidates",
            headers=headers,
            json={"count": 2, "instruction": "增加悬念"},
        )

    assert first.status_code == replay.status_code == 202
    assert replay.json() == first.json()
    assert len(calls) == 1


async def _awaitable(value):
    return value


async def _prepare_empty_run(novel_id: str):
    return {"novel_id": novel_id}


def _event_graph():
    class Snapshot:
        values = {"chapters": []}
        next = ()
        tasks = ()

    class Graph:
        async def astream(self, payload, config, *, stream_mode):
            yield {"world_builder": {"ok": True}}
            yield {"scene_writer": {"ok": True}}

        async def aget_state(self, config):
            return Snapshot()

    return Graph()
