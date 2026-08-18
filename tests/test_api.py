"""API 服务集成测试(httpx ASGI 传输 + 假 LLM,不依赖 API Key)。

覆盖:小说 CRUD、run 流(NDJSON 事件序)、interrupt 暂停、resume 定稿、
非暂停态 resume 的 409、不存在的小说 404。
"""

import asyncio
import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from api import server


@pytest.fixture
async def api_env(tmp_path, monkeypatch):
    """隔离的 API 环境:独立 SQLite + 重置图注册表 + 注入图定稿存储。"""
    from config import Config
    from memory.sql_store import NovelStore

    cfg = Config(
        sqlite_db_path=str(tmp_path / "api.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        model_secret_key_path=str(tmp_path / "data" / "model-settings.key"),
        openai_api_key="test-openai-key",
    )
    cfg.ensure_dirs()
    isolated = NovelStore(cfg)
    monkeypatch.setattr(server, "cfg", cfg)
    monkeypatch.setattr(server, "store", isolated)
    monkeypatch.setattr("graph.nodes._store", isolated)  # 定稿持久化同库
    server._novel_locks.clear()
    async with server.lifespan(server.app):
        yield server


@pytest.fixture
def fake_llm_7(monkeypatch):
    """一轮完整章节的固定回复。"""
    fake = FakeListChatModel(
        responses=[
            "```yaml\n世界观名称: 测试\n```",
            "- name: 林寒\n  role: 主角\n",
            "- chapter: 1\n  title: 雾起\n  estimated_words: 100\n",
            "- scene_number: 1\n  goal: 进入雾都\n  conflict: 城门盘查\n"
            "  turn: 发现追兵\n  location: 城门\n  characters: [林寒]\n"
            "  emotion: 紧张\n  estimated_words: 100\n",
            "初稿正文。",
            "初稿润色。",
            "[]",
        ],
        sleep=0.01,
    )
    for mod, attr in [
        ("agents.world_builder", "get_llm"),
        ("agents.character_designer", "get_llm"),
        ("agents.plot_planner", "get_analyzer_llm"),
        ("agents.scene_planner", "get_analyzer_llm"),
        ("agents.scene_writer", "get_llm"),
        ("agents.scene_rewriter", "get_llm"),
        ("agents.style_editor", "get_llm"),
        ("agents.consistency_checker", "get_analyzer_llm"),
    ]:
        monkeypatch.setattr(f"{mod}.{attr}", lambda **kw: fake)
    return fake


async def test_healthz(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        assert (await c.get("/healthz")).json() == {"status": "ok"}


def test_production_config_rejects_anonymous_mode():
    from config import Config

    unsafe = Config(app_environment="production", auth_enabled=False)
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        server._validate_production_config(unsafe)

    safe = Config(
        app_environment="production",
        auth_enabled=True,
        auth_rate_limit_window_seconds=60,
        auth_rate_limit_max_attempts=10,
    )
    server._validate_production_config(safe)


async def test_operations_readiness_audit_and_auth_rate_limit(api_env):
    from httpx import ASGITransport, AsyncClient

    api_env.cfg.auth_enabled = True
    api_env.cfg.auth_rate_limit_max_attempts = 3
    api_env.cfg.auth_rate_limit_window_seconds = 60
    api_env.cfg.sensitive_rate_limit_max_attempts = 1
    api_env.cfg.sensitive_rate_limit_window_seconds = 60
    api_env.store.clear_auth_rate_limits()
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        readiness = await c.get("/readyz")
        metrics = await c.get("/metrics")
        registered = (await c.post("/api/auth/register", json={
            "username": "ops_owner",
            "password": "ops-password",
            "tenant_name": "运维工作区",
        })).json()
        api_env.store.clear_auth_rate_limits()
        headers = {"Authorization": f"Bearer {registered['access_token']}"}
        novel = (await c.post("/api/novels", headers=headers, json={
            "title": "审计作品", "inspiration": "验证操作审计", "total_chapters": 1,
        })).json()
        api_env.store.create_run_job("job-monitoring", novel["id"], "run", {})
        api_env.store.clear_auth_rate_limits()
        audit = await c.get("/api/audit/logs", headers=headers)
        summary = await c.get("/api/monitoring/summary", headers=headers)
        first_export = await c.get(f"/api/novels/{novel['id']}/export?format=txt", headers=headers)
        limited_export = await c.get(f"/api/novels/{novel['id']}/export?format=txt", headers=headers)
        first = await c.post("/api/auth/login", json={
            "identifier": "ops_owner", "password": "wrong-password",
        })
        second = await c.post("/api/auth/login", json={
            "identifier": "ops_owner", "password": "wrong-password",
        })
        third = await c.post("/api/auth/login", json={
            "identifier": "ops_owner", "password": "wrong-password",
        })
        limited = await c.post("/api/auth/login", json={
            "identifier": "ops_owner", "password": "wrong-password",
        })

    assert readiness.status_code == 200
    assert readiness.json()["checks"]["sqlite"]["status"] == "ok"
    assert readiness.json()["checks"]["schema"]["status"] == "ok"
    assert "novel_agent_requests_total" in metrics.text
    assert "novel_agent_request_duration_ms_count" in metrics.text
    assert audit.status_code == 200
    assert {item["tenant_id"] for item in audit.json()["logs"]} == {registered["user"]["tenant_id"]}
    assert {item["action"] for item in audit.json()["logs"]} >= {"auth.registered", "http.post"}
    assert summary.status_code == 200
    assert summary.json()["run_jobs"]["queued"] == 1
    assert first_export.status_code == 200
    assert limited_export.status_code == 429
    assert first.status_code == second.status_code == third.status_code == 401
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    api_env.store.clear_auth_rate_limits()


async def test_auth_login_tenant_isolation_and_viewer_permissions(api_env):
    import sqlite3

    from httpx import ASGITransport, AsyncClient
    api_env.cfg.auth_enabled = True
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        alice = (await c.post("/api/auth/register", json={
            "username": "alice_auth",
            "email": "alice@example.test",
            "password": "alice-password",
            "tenant_name": "Alice 工作区",
        })).json()
        bob = (await c.post("/api/auth/register", json={
            "username": "bob_auth",
            "email": "bob@example.test",
            "password": "bob-password",
            "tenant_name": "Bob 工作区",
        })).json()
        alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
        bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}
        with sqlite3.connect(api_env.store.db_path) as conn:
            stored_token = conn.execute(
                "SELECT token_hash FROM sessions WHERE user_id = ?",
                (alice["user"]["id"],),
            ).fetchone()[0]
        assert stored_token != alice["access_token"]
        assert len(stored_token) == 64
        created = await c.post("/api/novels", headers=alice_headers, json={
            "title": "Alice 的作品", "genre": "科幻", "inspiration": "隔离测试", "total_chapters": 1,
        })
        assert created.status_code == 200
        novel_id = created.json()["id"]

        assert (await c.get("/api/auth/me", headers=alice_headers)).json()["user"]["username"] == "alice_auth"
        assert (await c.get("/api/novels", headers=bob_headers)).json() == []
        assert (await c.get(f"/api/novels/{novel_id}", headers=bob_headers)).status_code == 404
        job = api_env.store.create_run_job("job-auth-scope", novel_id, "run", {})
        assert (await c.get(f"/api/jobs/{job['id']}", headers=bob_headers)).status_code == 404
        benchmark = await c.post("/api/evaluations/benchmarks", headers=alice_headers, json={})
        assert benchmark.status_code == 200
        assert (await c.get("/api/evaluations/benchmarks", headers=bob_headers)).json() == []
        profile = await c.post("/api/model-settings/profiles", headers=alice_headers, json={
            "name": "Alice 模型",
            "provider": "openai",
            "base_url": "",
            "api_key": "",
            "chat_models": ["gpt-test"],
            "embedding_models": ["embed-test"],
        })
        assert profile.status_code == 201
        assert (await c.get("/api/model-settings", headers=bob_headers)).json()["profiles"] == []
        assert (await c.post("/api/novels", headers={"Authorization": "Bearer invalid"}, json={
            "title": "不应创建", "inspiration": "无",
        })).status_code == 401

        member = (await c.post("/api/auth/users", headers=alice_headers, json={
            "username": "viewer_auth",
            "email": "viewer@example.test",
            "password": "viewer-password",
            "display_name": "只读成员",
            "role": "editor",
        })).json()
        viewer_id = member["user"]["id"]
        members = (await c.get("/api/auth/users", headers=alice_headers)).json()["users"]
        assert {item["username"] for item in members} == {"alice_auth", "viewer_auth"}
        editor = (await c.post("/api/auth/login", json={
            "identifier": "viewer_auth", "password": "viewer-password",
        })).json()
        editor_headers = {"Authorization": f"Bearer {editor['access_token']}"}
        assert (await c.post("/api/novels", headers=editor_headers, json={
            "title": "编辑可写", "inspiration": "权限", "total_chapters": 1,
        })).status_code == 200
        assert (await c.delete(f"/api/novels/{novel_id}", headers=editor_headers)).status_code == 403
        updated = await c.put(
            f"/api/auth/users/{viewer_id}/role",
            headers=alice_headers,
            json={"role": "viewer"},
        )
        assert updated.status_code == 200
        viewer = (await c.post("/api/auth/login", json={
            "identifier": "viewer_auth", "password": "viewer-password",
        })).json()
        viewer_headers = {"Authorization": f"Bearer {viewer['access_token']}"}
        assert (await c.post("/api/novels", headers=viewer_headers, json={
            "title": "只读不可写", "inspiration": "权限", "total_chapters": 1,
        })).status_code == 403
        assert (await c.post("/api/auth/logout", headers=viewer_headers)).status_code == 200
        assert (await c.get("/api/auth/me", headers=viewer_headers)).status_code == 401


async def test_model_trace_endpoint_returns_metadata_only(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "轨迹测试", "genre": "科幻", "inspiration": "测试调用轨迹", "total_chapters": 1,
        })).json()
        api_env.app.state.model_settings_store.record_model_call(
            novel_id=created["id"],
            agent="scene_writer",
            purpose="creative",
            provider="openai",
            model_name="gpt-test",
            attempt=1,
            fallback_used=False,
            success=True,
            duration_ms=18,
            input_tokens=5,
            output_tokens=8,
            usage_estimated=False,
            call_id="call-api",
            trace_id="trace-api",
            input_hash="input-api",
            output_hash="output-api",
            input_chars=120,
            output_chars=240,
        )
        response = await c.get(f"/api/novels/{created['id']}/traces?agent=scene_writer")

    assert response.status_code == 200
    assert response.json()[0]["trace_id"] == "trace-api"
    assert response.json()[0]["input_hash"] == "input-api"
    assert "content" not in response.json()[0]


async def test_evaluation_benchmark_api_runs_and_lists_history(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = await c.post("/api/evaluations/benchmarks", json={"include_judge": False})
        assert created.status_code == 200
        run = created.json()
        assert run["status"] == "passed"
        assert len(run["cases"]) == 5
        history = await c.get("/api/evaluations/benchmarks?limit=10")
        detail = await c.get(f"/api/evaluations/benchmarks/{run['id']}")

    assert history.status_code == 200
    assert history.json()[0]["id"] == run["id"]
    assert detail.status_code == 200
    assert detail.json()["input_hash"] == run["input_hash"]


async def test_memory_quality_and_rebuild_api_are_tenant_scoped(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    class FakeMemory:
        records = []

        def __init__(self, novel_id):
            self.novel_id = novel_id
            self.records = list(type(self).records)

        def list_records(self):
            return self.records

        def search_similar(self, query, k=5):
            return [
                {"id": item["id"], "content": item["content"], "metadata": item["metadata"], "distance": 0.1}
                for item in self.records[:k]
            ]

        def clear(self):
            self.records = []
            type(self).records = []

        def store_content(self, content, metadata=None, content_id=None):
            item = {"id": content_id, "content": content, "metadata": {**(metadata or {}), "_memory_id": content_id}}
            self.records.append(item)
            type(self).records.append(item)

    monkeypatch.setattr(api_env, "NovelMemory", FakeMemory)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "记忆评测", "inspiration": "检索质量", "total_chapters": 1,
        })).json()
        nid = created["id"]
        api_env.store.save_chapter(
            novel_id=nid,
            chapter_number=1,
            title="雾起",
            content="林寒进入雾都。",
            summary="林寒进入雾都",
            status="final",
        )
        evaluated = await c.post(f"/api/novels/{nid}/memory/evaluate", json={"k": 3})
        rebuilt = await c.post(f"/api/novels/{nid}/memory/rebuild", json={"evaluate": True, "k": 3})
        history = await c.get(f"/api/novels/{nid}/memory/quality")

    assert evaluated.status_code == 200
    assert evaluated.json()["report"]["schema_version"] == "memory-quality-v1"
    assert rebuilt.status_code == 200
    assert rebuilt.json()["rebuild"]["record_count"] >= 1
    assert history.status_code == 200
    assert len(history.json()["runs"]) == 2


async def test_novel_export_formats_and_backup_import(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "导出测试", "genre": "武侠", "inspiration": "备份", "total_chapters": 1,
        })).json()
        nid = created["id"]
        api_env.store.save_chapter(
            novel_id=nid,
            chapter_number=1,
            title="雾起",
            content="林寒进入雾都。",
            summary="林寒进入雾都",
            status="final",
        )
        responses = {
            fmt: await c.get(f"/api/novels/{nid}/export?format={fmt}")
            for fmt in ("markdown", "txt", "docx", "epub", "backup")
        }
        backup = responses["backup"].content
        imported = await c.post(
            "/api/novels/import",
            files={"file": ("导出测试.novel-backup.zip", backup, "application/zip")},
        )

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["docx"].headers["content-type"].startswith("application/vnd.openxmlformats")
    assert responses["epub"].headers["content-type"].startswith("application/epub+zip")
    assert imported.status_code == 200
    assert imported.json()["imported_chapters"] == 1
    assert imported.json()["novel"]["title"] == "导出测试"


async def test_import_rejects_files_over_configured_limit(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(api_env.cfg, "max_import_bytes", 4)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post(
            "/api/novels/import",
            files={"file": ("large.txt", b"12345", "text/plain")},
        )
    assert response.status_code == 413


async def test_import_uses_highest_chapter_number_for_progress(api_env):
    from httpx import ASGITransport, AsyncClient

    content = "# 跳章作品\n\n第1章 起点\n第一章正文\n\n第10章 终点\n第十章正文"
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        imported = await c.post(
            "/api/novels/import",
            files={"file": ("jump.md", content.encode(), "text/markdown")},
        )
        assert imported.status_code == 200, imported.text
        novel_id = imported.json()["novel"]["id"]
        state = await c.get(f"/api/novels/{novel_id}/state")

    assert imported.json()["novel"]["total_chapters"] == 10
    assert state.json()["total_chapters"] == 10
    assert state.json()["current_chapter"] == 11


async def test_password_encrypted_backup_export_and_import(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    class MemoryStub:
        def __init__(self, novel_id):
            self.novel_id = novel_id
            self.records = []

        def list_records(self):
            return list(self.records)

        def clear(self):
            self.records = []

        def store_content(self, content, metadata=None, content_id=None):
            self.records.append({"id": content_id, "content": content, "metadata": metadata or {}})

    monkeypatch.setattr(api_env, "NovelMemory", MemoryStub)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "加密备份", "inspiration": "安全恢复", "total_chapters": 1,
        })).json()
        api_env.store.save_chapter(
            novel_id=created["id"],
            chapter_number=1,
            title="密文",
            content="只有密码持有者可以恢复。",
            summary="加密恢复",
            status="final",
        )
        exported = await c.get(
            f"/api/novels/{created['id']}/export",
            params={"format": "backup"},
            headers={"X-Backup-Password": "secret-passphrase"},
        )
        imported = await c.post(
            "/api/novels/import",
            files={"file": ("backup.novel-backup.enc", exported.content, "application/octet-stream")},
            data={"password": "secret-passphrase"},
        )
        rejected = await c.post(
            "/api/novels/import",
            files={"file": ("backup.novel-backup.enc", exported.content, "application/octet-stream")},
            data={"password": "wrong"},
        )

    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/octet-stream")
    assert imported.status_code == 200
    assert imported.json()["novel"]["title"] == "加密备份"
    assert rejected.status_code == 422


async def test_large_transfer_import_and_export_use_persistent_jobs(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    class MemoryStub:
        def __init__(self, novel_id):
            self.records = []

        def list_records(self):
            return list(self.records)

        def clear(self):
            self.records = []

        def store_content(self, content, metadata=None, content_id=None):
            self.records.append({"id": content_id, "content": content, "metadata": metadata or {}})

    monkeypatch.setattr(api_env, "NovelMemory", MemoryStub)
    monkeypatch.setattr(api_env.cfg, "background_transfer_bytes", 1)
    original_to_thread = asyncio.to_thread
    threaded_calls = []

    async def tracked_to_thread(func, /, *args, **kwargs):
        threaded_calls.append(getattr(func, "__name__", type(func).__name__))
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(api_env.asyncio, "to_thread", tracked_to_thread)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        imported = await c.post(
            "/api/novels/import",
            files={"file": ("large.txt", "# 后台导入\n\n第一章\n正文内容".encode(), "text/plain")},
        )
        assert imported.status_code == 202
        import_job_id = imported.json()["job"]["id"]
        for _ in range(40):
            import_job = await c.get(f"/api/transfers/{import_job_id}")
            if import_job.json()["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.02)
        assert import_job.json()["status"] == "completed", import_job.json()
        imported_novel = import_job.json()["result"]["novel"]

        exported = await c.get(
            f"/api/novels/{imported_novel['id']}/export",
            params={"format": "backup"},
        )
        assert exported.status_code == 202
        export_job_id = exported.json()["job"]["id"]
        for _ in range(40):
            export_job = await c.get(f"/api/transfers/{export_job_id}")
            if export_job.json()["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.02)
        assert export_job.json()["status"] == "completed", export_job.json()
        downloaded = await c.get(f"/api/transfers/{export_job_id}/download")

    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    assert "parse_import_bytes" in threaded_calls
    assert "export_novel_bytes" in threaded_calls



async def test_novel_crud_flow(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "雾中剑", "genre": "武侠", "inspiration": "失忆剑客",
            "total_chapters": 1, "style": "gu_long",
            "creative_brief": {
                "target_audience": "成年武侠读者",
                "point_of_view": "multiple",
                "themes": ["身份", "传承"],
                "intensity": {"action": 5, "darkness": 3},
            },
        })).json()
        nid = created["id"]
        assert created["inspiration"] == "失忆剑客"
        assert created["creative_brief"]["target_audience"] == "成年武侠读者"
        assert created["creative_brief"]["point_of_view"] == "multiple"

        assert len((await c.get("/api/novels")).json()) == 1
        detail = (await c.get(f"/api/novels/{nid}")).json()
        assert detail["title"] == "雾中剑"
        assert detail["creative_brief"]["themes"] == ["身份", "传承"]

        state = (await c.get(f"/api/novels/{nid}/state")).json()
        assert state["creative_brief"]["intensity"]["action"] == 5

        assert (await c.get("/api/novels/none")).status_code == 404
        assert (await c.post("/api/novels/{none}/run".replace("{none}", "none"))).status_code == 404


async def test_create_novel_keeps_backward_compatible_brief_defaults(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post("/api/novels", json={
            "title": "旧客户端作品",
            "inspiration": "未发送创作约束",
        })

    assert response.status_code == 200
    assert response.json()["creative_brief"]["age_rating"] == "teen"
    assert response.json()["creative_brief"]["point_of_view"] == "third_limited"


async def test_create_novel_rejects_invalid_creative_brief(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post("/api/novels", json={
            "title": "非法约束",
            "inspiration": "测试校验",
            "creative_brief": {
                "point_of_view": "second_person",
                "intensity": {"darkness": 6},
            },
        })

    assert response.status_code == 422


async def test_creative_brief_update_versions_and_rejects_stale_writes(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "约束版本",
            "inspiration": "测试约束更新",
        })).json()
        nid = created["id"]
        updated = await c.put(
            f"/api/novels/{nid}/creative-brief",
            json={
                "expected_version": 1,
                "change_summary": "改为第一人称开放结局",
                "creative_brief": {
                    "target_audience": "推理读者",
                    "point_of_view": "first_person",
                    "ending_tone": "open",
                    "themes": ["记忆与身份"],
                },
            },
        )
        conflict = await c.put(
            f"/api/novels/{nid}/creative-brief",
            json={
                "expected_version": 1,
                "creative_brief": {"target_audience": "旧页面提交"},
            },
        )
        unchanged = await c.put(
            f"/api/novels/{nid}/creative-brief",
            json={
                "expected_version": 2,
                "creative_brief": updated.json()["creative_brief"],
            },
        )
        versions = (await c.get(
            f"/api/novels/{nid}/creative-brief/versions"
        )).json()

    assert updated.status_code == 200
    assert updated.json()["creative_brief_version"] == 2
    assert updated.json()["changed"] is True
    assert updated.json()["requires_revalidation"] is False
    assert conflict.status_code == 409
    assert "当前版本为 v2" in conflict.json()["detail"]
    assert unchanged.json()["changed"] is False
    assert unchanged.json()["creative_brief_version"] == 2
    assert [item["version_number"] for item in versions] == [2, 1]
    assert versions[0]["change_summary"] == "改为第一人称开放结局"


async def test_creative_brief_update_preserves_review_checkpoint_and_requires_recheck(
    api_env,
    fake_llm_7,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    from agents.chapter_candidate import chapter_candidate_source_hash

    async def no_issues(self, **kwargs):
        return []

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "审查中更新",
            "inspiration": "测试 checkpoint 同步",
            "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")
        before = await api_env.app.state.graph.aget_state(
            {"configurable": {"thread_id": nid}}
        )
        original_content = before.values["current_draft"]["content"]
        candidate = api_env.store.save_chapter_candidate(
            nid,
            1,
            generation_id="generation-before-brief-update",
            candidate_number=1,
            source_hash=chapter_candidate_source_hash(before.values),
            instruction="旧约束候选",
            title="旧候选",
            content="旧约束生成的正文",
            scores={"structure": 80},
        )

        updated = await c.put(
            f"/api/novels/{nid}/creative-brief",
            json={
                "expected_version": 1,
                "change_summary": "禁止梦境解谜",
                "creative_brief": {
                    "target_audience": "硬核推理读者",
                    "avoid_content": ["梦境解释一切"],
                    "intensity": {"mystery": 5},
                },
            },
        )
        review_state = (await c.get(f"/api/novels/{nid}/state")).json()
        blocked = await c.post(
            f"/api/novels/{nid}/jobs/resume",
            json={"feedback": "approve"},
        )

        monkeypatch.setattr("graph.nodes.ConsistencyCheckerAgent.check", no_issues)
        recheck = await c.post(
            f"/api/novels/{nid}/jobs/resume",
            json={"feedback": "recheck"},
        )
        result = await _wait_for_run_job(c, recheck.json()["id"])
        rechecked_state = (await c.get(f"/api/novels/{nid}/state")).json()

    assert updated.status_code == 200
    assert updated.json()["creative_brief_version"] == 2
    assert updated.json()["requires_revalidation"] is True
    assert updated.json()["stale_candidate_count"] == 1
    assert review_state["status"] == "human_review"
    assert review_state["creative_brief_review_required"] is True
    assert review_state["current_draft"]["content"] == original_content
    assert next(
        item for item in review_state["chapter_candidates"] if item["id"] == candidate["id"]
    )["status"] == "stale"
    assert blocked.status_code == 409
    assert "必须先按新约束重新质检" in blocked.json()["detail"]
    assert recheck.status_code == 202
    assert result["job"]["status"] == "waiting_review"
    assert rechecked_state["status"] == "human_review"
    assert rechecked_state["creative_brief_review_required"] is False
    assert rechecked_state["creative_brief_version"] == 2


async def test_delete_novel_removes_it_and_returns_404_afterward(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "删除测试", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        deleted = await c.delete(f"/api/novels/{nid}")
        missing = await c.get(f"/api/novels/{nid}")

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "novel_id": nid}
    assert missing.status_code == 404


async def test_delete_missing_novel_returns_404(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.delete("/api/novels/missing")
    assert response.status_code == 404


async def test_run_interrupt_resume_flow(api_env, fake_llm_7):
    """全链路:run 流输出节点事件 + interrupt → resume approve → end。"""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "雾中剑", "inspiration": "失忆剑客", "total_chapters": 1, "style": "gu_long",
        })).json()["id"]

        # run:流式 NDJSON,直至 interrupt
        lines = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/run")).aiter_lines()
            if line.strip()
        ]
        nodes = [e["node"] for e in lines if e["type"] == "node_done" and e["node"] != "orchestrator"]
        assert nodes == ["world_builder", "character_designer", "plot_planner",
                         "scene_planner", "scene_writer", "style_editor", "consistency_checker"]

        interrupt_ev = lines[-1]
        assert interrupt_ev["type"] == "interrupt"
        assert interrupt_ev["title"] == "雾起"
        assert interrupt_ev["scene_plan"][0]["goal"] == "进入雾都"

        # 已暂停时必须显式走 resume,不能用 run 重复驱动同一检查点
        rerun = await c.post(f"/api/novels/{nid}/run")
        assert rerun.status_code == 409

        # 未暂停前对已结束流 resume:图暂停在 human_review,可 resume
        resume_lines = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})).aiter_lines()
            if line.strip()
        ]
        assert resume_lines[-1]["type"] == "end"
        assert resume_lines[-1]["chapters_done"] == 1

        # 已至 END 再 resume → 409
        assert (await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})).status_code == 409

        # 定稿已入 SQLite
        detail = (await c.get(f"/api/novels/{nid}")).json()
        assert len(detail["chapters"]) == 1
        assert detail["chapters"][0]["status"] == "final"
        assert detail["chapters"][0]["summary"].startswith("林寒穿过雾都城门")
        assert detail["chapters"][0]["digest"]["digest_version"] == "chapter-digest-v1"
        assert detail["chapters"][0]["scene_plan"][0]["goal"] == "进入雾都"
        state = (await c.get(f"/api/novels/{nid}/state")).json()
        audits = (await c.get(f"/api/novels/{nid}/book-audits")).json()
        memory = (await c.get(f"/api/novels/{nid}/memory")).json()
        assert state["book_audit"]["judge_scores"]["plot_coherence"] == 88
        assert state["memory"] == {
            "schema_version": "book-memory-v1",
            "chapters": 1,
            "arcs": 1,
        }
        assert memory["completed_chapters"] == 1
        assert memory["arcs"][0]["start_chapter"] == 1
        assert len(audits) == 1
        assert audits[0]["report"]["manuscript_hash"] == audits[0]["manuscript_hash"]


async def test_completed_book_can_revise_a_final_chapter_and_reaudit(
    api_env,
    fake_llm_7,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "终稿返修",
            "inspiration": "失忆剑客",
            "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")
        await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})
        original = api_env.store.get_chapter(nid, 1)
        first_audit = api_env.store.get_latest_book_audit(nid)

        revision_model = FakeListChatModel(
            responses=["返修正文。", "返修正文润色。", "[]"],
        )
        monkeypatch.setattr("agents.scene_writer.get_llm", lambda **kw: revision_model)
        monkeypatch.setattr("agents.style_editor.get_llm", lambda **kw: revision_model)
        monkeypatch.setattr(
            "agents.consistency_checker.get_analyzer_llm",
            lambda **kw: revision_model,
        )
        started = await c.post(
            f"/api/novels/{nid}/jobs/book-revision",
            json={"chapter_number": 1, "feedback": "强化结局的角色选择"},
        )
        assert started.status_code == 202
        waiting = await _wait_for_run_job(c, started.json()["id"])
        review_state = (await c.get(f"/api/novels/{nid}/state")).json()

        assert waiting["job"]["status"] == "waiting_review"
        assert review_state["status"] == "human_review"
        assert review_state["current_chapter"] == 1
        assert review_state["current_draft"]["content"] == "返修正文润色。"
        assert api_env.store.get_chapter(nid, 1)["content"] == original["content"]

        approved = await c.post(
            f"/api/novels/{nid}/jobs/resume",
            json={"feedback": "approve"},
        )
        final = await _wait_for_run_job(c, approved.json()["id"])
        final_state = (await c.get(f"/api/novels/{nid}/state")).json()
        audits = (await c.get(f"/api/novels/{nid}/book-audits")).json()

    assert final["job"]["status"] == "completed"
    assert final_state["status"] == "completed"
    assert final_state["chapters_done"] == 1
    assert final_state["current_chapter"] == 2
    assert api_env.store.get_chapter(nid, 1)["content"] == "返修正文润色。"
    assert final_state["next"] == []
    assert len(audits) == 2
    assert audits[0]["manuscript_hash"] != first_audit["manuscript_hash"]
    assert "book_revision_final" in {
        item["source"] for item in api_env.store.list_chapter_versions(nid, 1)
    }


async def test_digest_failure_returns_retryable_human_review(api_env, fake_llm_7, monkeypatch):
    """终稿提炼失败通过原有人工审查协议暴露，修复后可再次批准。"""
    from httpx import ASGITransport, AsyncClient

    from graph import nodes

    class FailingDigest:
        async def digest(self, **kwargs):
            raise RuntimeError("digest provider unavailable")

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "提炼重试", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")
        monkeypatch.setattr(nodes, "ChapterDigestAgent", FailingDigest)

        failed = [
            json.loads(line)
            async for line in (
                await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})
            ).aiter_lines()
            if line.strip()
        ]
        assert failed[-1]["type"] == "interrupt"
        assert "终稿事实提炼失败" in failed[-1]["persistence_error"]
        assert (await c.get(f"/api/novels/{nid}/state")).json()["status"] == "human_review"

        monkeypatch.setattr(nodes, "ChapterDigestAgent", __import__(
            "agents.chapter_digest", fromlist=["ChapterDigestAgent"]
        ).ChapterDigestAgent)
        recovered = [
            json.loads(line)
            async for line in (
                await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})
            ).aiter_lines()
            if line.strip()
        ]

    assert recovered[-1]["type"] == "end"


async def _wait_for_run_job(client, job_id: str, terminal: set[str] | None = None):
    terminal = terminal or {
        "waiting_review",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    }
    payload = None
    for _ in range(200):
        payload = (await client.get(f"/api/jobs/{job_id}/events")).json()
        if payload["job"]["status"] in terminal:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"后台任务未在预期时间结束:{payload}")


async def test_background_run_job_survives_request_and_replays_events(
    api_env,
    fake_llm_7,
):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "后台任务", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        created = await c.post(f"/api/novels/{nid}/jobs/run")
        assert created.status_code == 202
        job_id = created.json()["id"]

        result = await _wait_for_run_job(c, job_id)
        events = result["events"]
        state = (await c.get(f"/api/novels/{nid}/state")).json()
        resumed = await c.post(
            f"/api/novels/{nid}/jobs/resume",
            json={"feedback": "approve"},
        )
        final = await _wait_for_run_job(c, resumed.json()["id"])
        final_state = (await c.get(f"/api/novels/{nid}/state")).json()

    assert result["job"]["status"] == "waiting_review"
    assert events[0]["payload"]["type"] == "job_started"
    assert any(item["payload"].get("node") == "consistency_checker" for item in events)
    assert events[-1]["payload"]["type"] == "interrupt"
    assert state["status"] == "human_review"
    assert state["run_job"]["id"] == job_id
    assert final["job"]["status"] == "completed"
    assert final["events"][-1]["payload"]["type"] == "end"
    assert final_state["status"] == "completed"
    assert final_state["replan_proposal"]["status"] == "stable"


async def test_candidate_generation_keeps_checkpoint_untouched_and_selection_rechecks(
    api_env,
    fake_llm_7,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    async def fake_candidate(self, state, *, candidate_number, total_candidates, instruction=""):
        content = (
            f"候选{candidate_number}沿着城门石阶进入雾都，守卫的目光始终追着他的剑。\n\n"
            "远处钟声压过人群，他从一句含混的盘问里听见旧日暗号。\n\n"
            "追兵出现时，他没有逃向预定的街口，而是转身走进封闭的旧巷。"
        )
        scene_plan = [{
            "scene_number": 1,
            "goal": "进入雾都",
            "conflict": "城门盘查",
            "turn": "发现追兵",
            "location": "城门",
            "characters": ["林寒"],
            "emotion": "紧张",
            "estimated_words": len(content),
        }]
        return {
            "chapter_number": 1,
            "title": f"候选{candidate_number}",
            "content": content,
            "summary": f"第{candidate_number}种入城方案",
            "scene_plan": scene_plan,
            "scene_drafts": [{"scene_number": 1, "content": content}],
            "scores": {"structure": 92.0},
            "overall_score": 92.0,
            "evaluation_schema_version": "chapter-quality-v1",
        }

    async def no_issues(self, **kwargs):
        return []

    monkeypatch.setattr(server.ChapterCandidateAgent, "generate", fake_candidate)
    monkeypatch.setattr("graph.nodes.ConsistencyCheckerAgent.check", no_issues)

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "候选稿",
            "inspiration": "灵感",
            "total_chapters": 1,
        })).json()["id"]
        run = await c.post(f"/api/novels/{nid}/jobs/run")
        await _wait_for_run_job(c, run.json()["id"])
        before = await api_env.app.state.graph.aget_state(
            {"configurable": {"thread_id": nid}}
        )
        original_content = before.values["current_draft"]["content"]

        generated = await c.post(
            f"/api/novels/{nid}/jobs/candidates",
            json={"count": 2, "instruction": "增强悬念"},
        )
        assert generated.status_code == 202
        result = await _wait_for_run_job(c, generated.json()["id"])
        candidate_state = (await c.get(f"/api/novels/{nid}/state")).json()
        after = await api_env.app.state.graph.aget_state(
            {"configurable": {"thread_id": nid}}
        )

        assert result["job"]["status"] == "completed"
        assert after.values["current_draft"]["content"] == original_content
        assert list(after.next) == ["human_review"]
        assert len(candidate_state["chapter_candidates"]) == 2
        assert api_env.store.get_all_chapters(nid) == []

        chosen = candidate_state["chapter_candidates"][0]
        selected = await c.post(
            f"/api/novels/{nid}/jobs/resume",
            json={"candidate_id": chosen["id"]},
        )
        selected_result = await _wait_for_run_job(c, selected.json()["id"])
        selected_state = (await c.get(f"/api/novels/{nid}/state")).json()

        alternative = next(
            item for item in candidate_state["chapter_candidates"]
            if item["id"] != chosen["id"]
        )
        switched = await c.post(
            f"/api/novels/{nid}/jobs/resume",
            json={"candidate_id": alternative["id"]},
        )
        switched_result = await _wait_for_run_job(c, switched.json()["id"])
        switched_state = (await c.get(f"/api/novels/{nid}/state")).json()

    assert selected_result["job"]["status"] == "waiting_review"
    assert selected_state["current_draft"]["content"] == chosen["content"]
    assert switched_result["job"]["status"] == "waiting_review"
    assert switched_state["current_draft"]["content"] == alternative["content"]
    assert next(
        item for item in switched_state["chapter_candidates"]
        if item["id"] == alternative["id"]
    )["status"] == "selected"
    assert api_env.store.get_all_chapters(nid) == []


async def test_background_planning_review_jobs_resume_through_both_gates(
    api_env,
    fake_llm_7,
):
    """规划审批通过持久后台任务跨越蓝图与分镜两个暂停点。"""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "审批流",
            "inspiration": "先审后写",
            "total_chapters": 1,
            "planning_review_enabled": True,
        })).json()
        nid = created["id"]
        assert created["planning_review_enabled"] is True

        run = await c.post(f"/api/novels/{nid}/jobs/run")
        first = await _wait_for_run_job(c, run.json()["id"])
        blueprint_state = (await c.get(f"/api/novels/{nid}/state")).json()
        assert first["events"][-1]["payload"]["node"] == "blueprint_review"
        assert blueprint_state["status"] == "blueprint_review"
        assert blueprint_state["current_draft"] == {}
        assert [item["source"] for item in blueprint_state["planning_versions"]] == [
            "generated",
        ]

        blueprint = await c.post(f"/api/novels/{nid}/jobs/resume", json={
            "review_type": "blueprint_review",
            "world_bible": blueprint_state["world_bible"] + "\n审阅: 通过",
            "characters": blueprint_state["characters"],
            "outline": blueprint_state["outline"],
        })
        second = await _wait_for_run_job(c, blueprint.json()["id"])
        scene_state = (await c.get(f"/api/novels/{nid}/state")).json()
        assert second["events"][-1]["payload"]["node"] == "scene_review"
        assert scene_state["status"] == "scene_review"
        assert scene_state["current_draft"] == {}
        assert [item["source"] for item in scene_state["planning_versions"]] == [
            "generated",
        ]

        blueprint_versions = (await c.get(
            f"/api/novels/{nid}/planning/blueprint/versions"
        )).json()
        restored_blueprint = (await c.get(
            f"/api/novels/{nid}/planning/blueprint/versions/2"
        )).json()
        blueprint_diff = (await c.get(
            f"/api/novels/{nid}/planning/blueprint/versions/diff",
            params={"from_version": 1, "to_version": 2},
        )).json()
        assert [item["source"] for item in blueprint_versions] == ["generated", "approved"]
        assert "审阅: 通过" in restored_blueprint["payload"]["world_bible"]
        assert "审阅: 通过" in blueprint_diff["diff"]

        invalid = await c.post(f"/api/novels/{nid}/jobs/resume", json={
            "review_type": "scene_review",
            "scene_plan": [],
        })
        assert invalid.status_code == 422

        scene = await c.post(f"/api/novels/{nid}/jobs/resume", json={
            "review_type": "scene_review",
            "scene_plan": scene_state["scene_plan"],
        })
        third = await _wait_for_run_job(c, scene.json()["id"])
        final_state = (await c.get(f"/api/novels/{nid}/state")).json()
        assert third["events"][-1]["payload"]["node"] == "human_review"
        assert final_state["status"] == "human_review"
        assert "审阅: 通过" in final_state["world_bible"]
        scene_versions = (await c.get(
            f"/api/novels/{nid}/planning/scene/versions",
            params={"chapter_number": 1},
        )).json()
        assert [item["source"] for item in scene_versions] == ["generated", "approved"]


async def test_planning_version_persistence_failure_does_not_break_checkpoint(
    api_env,
    fake_llm_7,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    def fail_snapshot(*args, **kwargs):
        raise OSError("planning snapshot unavailable")

    monkeypatch.setattr(api_env.store, "save_planning_version", fail_snapshot)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "快照失败",
            "inspiration": "仍应暂停",
            "total_chapters": 1,
            "planning_review_enabled": True,
        })).json()["id"]
        run = await c.post(f"/api/novels/{nid}/jobs/run")
        result = await _wait_for_run_job(c, run.json()["id"])
        state = (await c.get(f"/api/novels/{nid}/state")).json()

    assert result["job"]["status"] == "waiting_review"
    assert result["events"][-1]["payload"]["node"] == "blueprint_review"
    assert state["status"] == "blueprint_review"
    assert state["planning_versions"] == []


async def test_background_job_event_cursor_and_active_job_conflict(
    api_env,
    fake_llm_7,
):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "事件续传", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        first = await c.post(f"/api/novels/{nid}/jobs/run")
        duplicate = await c.post(f"/api/novels/{nid}/jobs/run")
        result = await _wait_for_run_job(c, first.json()["id"])
        first_sequence = result["events"][0]["sequence"]
        replay = (await c.get(
            f"/api/jobs/{first.json()['id']}/events",
            params={"after_sequence": first_sequence},
        )).json()

    assert duplicate.status_code == 409
    assert replay["events"]
    assert all(item["sequence"] > first_sequence for item in replay["events"])


async def test_background_job_can_be_cancelled(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    slow = FakeListChatModel(responses=["```yaml\n世界观名称: 测试\n```"], sleep=1)
    monkeypatch.setattr("agents.world_builder.get_llm", lambda **kw: slow)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "取消任务", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        created = (await c.post(f"/api/novels/{nid}/jobs/run")).json()
        settings_write = await c.post(
            "/api/model-settings/profiles",
            json={
                "name": "Busy",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "chat_models": ["gpt-4o"],
                "embedding_models": ["text-embedding-3-small"],
            },
        )
        cancelled = await c.post(f"/api/jobs/{created['id']}/cancel")
        result = (await c.get(f"/api/jobs/{created['id']}/events")).json()

    assert cancelled.status_code == 200
    assert settings_write.status_code == 409
    assert cancelled.json()["status"] == "cancelled"
    assert result["events"][-1]["payload"]["type"] == "cancelled"


async def test_cancel_request_does_not_finish_job_owned_by_another_worker(api_env):
    from httpx import ASGITransport, AsyncClient

    api_env.store.create_novel("foreign-job", "跨进程任务")
    api_env.store.create_run_job("job-foreign", "foreign-job", "run")
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post("/api/jobs/job-foreign/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["cancel_requested"] is True
    api_env.store.update_run_job("job-foreign", status="cancelled")


async def test_background_canon_job_returns_to_review(
    api_env,
    fake_llm_7,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "后台 Canon", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        started = (await c.post(f"/api/novels/{nid}/jobs/run")).json()
        await _wait_for_run_job(c, started["id"])

        check_llm = FakeListChatModel(responses=["[]"])
        monkeypatch.setattr(
            "agents.consistency_checker.get_analyzer_llm",
            lambda **kwargs: check_llm,
        )
        created = await c.post(f"/api/novels/{nid}/jobs/canon", json={
            "action": "upsert_fact",
            "target_type": "fact",
            "subject": "守夜人",
            "value": "午夜换岗",
            "reason": "测试后台治理",
        })
        result = await _wait_for_run_job(c, created.json()["id"])
        canon = (await c.get(f"/api/novels/{nid}/canon")).json()

    assert created.status_code == 202
    assert result["job"]["status"] == "waiting_review"
    assert any(item["payload"].get("node") == "consistency_checker" for item in result["events"])
    assert result["events"][-1]["payload"]["type"] == "interrupt"
    assert any(item["subject"] == "守夜人" for item in canon["facts"])


async def test_resume_missing_novel_returns_404(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post("/api/novels/missing/resume", json={"feedback": "approve"})
    assert response.status_code == 404


async def test_state_missing_novel_returns_404(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.get("/api/novels/missing/state")
    assert response.status_code == 404


async def test_state_for_new_novel_is_idle(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "状态测试", "inspiration": "灵感", "total_chapters": 2,
        })).json()["id"]
        response = await c.get(f"/api/novels/{nid}/state")

    state = response.json()
    assert state["status"] == "idle"
    assert state["chapters_done"] == 0
    assert state["total_chapters"] == 2
    assert state["versions"] == []
    assert state["model_usage"]["total_tokens"] == 0
    assert state["canon"] == {
        "version": 0,
        "world_facts": 0,
        "characters": 0,
        "timeline_entries": 0,
        "confirmed_facts": 0,
        "deprecated_facts": 0,
        "aliases": 0,
        "audit_entries": 0,
        "narrative_threads": 0,
        "open_threads": 0,
        "resolved_threads": 0,
        "overdue_threads": 0,
    }


async def test_state_for_human_review_contains_draft(api_env, fake_llm_7):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "审查状态", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")
        response = await c.get(f"/api/novels/{nid}/state")

    state = response.json()
    assert state["status"] == "human_review"
    assert state["current_draft"]["title"] == "雾起"
    assert state["current_draft"]["scene_plan"][0]["goal"] == "进入雾都"
    assert state["next"] == ["human_review"]
    assert state["canon"]["version"] == 3
    assert state["canon"]["world_facts"] == 1
    assert state["canon"]["characters"] == 1
    assert state["canon"]["timeline_entries"] == 1
    assert state["canon"]["confirmed_facts"] == 0
    assert len(state["versions"]) == 1
    assert state["versions"][0]["source"] == "initial"


async def test_canon_api_reads_validates_updates_and_rechecks(api_env, fake_llm_7, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "Canon 治理",
            "inspiration": "灵感",
            "total_chapters": 1,
        })).json()["id"]

        assert (await c.get("/api/novels/missing/canon")).status_code == 404
        assert (await c.post(f"/api/novels/{nid}/canon", json={
            "action": "upsert_fact",
            "target_type": "fact",
            "subject": "守夜人",
            "value": "午夜换岗",
            "reason": "测试",
        })).status_code == 409

        await c.post(f"/api/novels/{nid}/run")
        canon = (await c.get(f"/api/novels/{nid}/canon")).json()
        assert canon["version"] == 3
        assert canon["audit"] == []

        invalid = await c.post(f"/api/novels/{nid}/canon", json={
            "action": "deprecate_fact",
            "target_type": "fact",
            "target_id": "missing",
            "reason": "无效目标",
        })
        assert invalid.status_code == 422
        assert "不存在" in invalid.json()["detail"]

        check_llm = FakeListChatModel(responses=["[]"])
        monkeypatch.setattr(
            "agents.consistency_checker.get_analyzer_llm",
            lambda **kwargs: check_llm,
        )
        lines = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/canon", json={
                "action": "upsert_fact",
                "target_type": "fact",
                "subject": "守夜人",
                "kind": "organization",
                "value": "只在午夜换岗",
                "reason": "固定当前章节的时间约束",
            })).aiter_lines()
            if line.strip()
        ]

        assert [item.get("node") for item in lines if item["type"] == "node_done"] == [
            "human_review",
            "consistency_checker",
        ]
        assert lines[-1]["type"] == "interrupt"
        updated = (await c.get(f"/api/novels/{nid}/canon")).json()
        state = (await c.get(f"/api/novels/{nid}/state")).json()

        thread_lines = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/canon", json={
                "action": "upsert_thread",
                "title": "失踪王印",
                "description": "追查王印去向",
                "kind": "mystery",
                "priority": "minor",
                "introduced_chapter": 1,
                "due_chapter": 1,
                "reason": "登记剧情债务",
            })).aiter_lines()
            if line.strip()
        ]
        assert thread_lines[-1]["type"] == "interrupt"
        thread_canon = (await c.get(f"/api/novels/{nid}/canon")).json()
        thread_id = thread_canon["narrative_threads"][0]["id"]

        beat_lines = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/canon", json={
                "action": "upsert_thread_beat",
                "target_id": thread_id,
                "chapter": 1,
                "beat_action": "develop",
                "description": "发现伪造印文",
                "reason": "增加推进节点",
            })).aiter_lines()
            if line.strip()
        ]
        assert beat_lines[-1]["type"] == "interrupt"
        thread_canon = (await c.get(f"/api/novels/{nid}/canon")).json()
        thread_state = (await c.get(f"/api/novels/{nid}/state")).json()

    assert updated["facts"][0]["value"] == "只在午夜换岗"
    assert updated["audit"][0]["action"] == "upsert_fact"
    assert updated["audit"][0]["reason"] == "固定当前章节的时间约束"
    assert state["canon"]["confirmed_facts"] == 1
    assert state["canon"]["audit_entries"] == 1
    assert thread_canon["narrative_threads"][0]["beats"][0]["action"] == "develop"
    assert thread_canon["audit"][-1]["action"] == "upsert_thread_beat"
    assert thread_state["canon"]["narrative_threads"] == 1
    assert thread_state["canon"]["open_threads"] == 1


async def test_frontend_cors_allows_vite_origin(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.options(
            "/api/novels",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_model_profile_api_never_returns_plaintext_key(api_env):
    from httpx import ASGITransport, AsyncClient

    payload = {
        "name": "DeepSeek",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-api-secret",
        "chat_models": ["deepseek-chat"],
        "embedding_models": [],
    }
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = await c.post("/api/model-settings/profiles", json=payload)
        listed = await c.get("/api/model-settings")
        updated = await c.put(
            f"/api/model-settings/profiles/{created.json()['id']}",
            json={**payload, "name": "DeepSeek 主服务", "api_key": ""},
        )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["has_api_key"] is True
    assert "sk-api-secret" not in created.text
    assert "sk-api-secret" not in listed.text
    assert "sk-api-secret" not in updated.text


async def test_model_routes_are_atomic_and_routed_profile_cannot_be_deleted(api_env):
    from httpx import ASGITransport, AsyncClient

    profile = {
        "name": "OpenAI",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "chat_models": ["gpt-4o"],
        "embedding_models": ["text-embedding-3-small"],
    }
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        profile_id = (await c.post("/api/model-settings/profiles", json=profile)).json()["id"]
        target = {"profile_id": profile_id, "model_name": "gpt-4o"}
        routes = await c.put(
            "/api/model-settings/routes",
            json={
                "creative": target,
                "analysis": target,
                "embedding": {"profile_id": profile_id, "model_name": "text-embedding-3-small"},
            },
        )
        deleted = await c.delete(f"/api/model-settings/profiles/{profile_id}")

    assert routes.status_code == 200
    assert set(routes.json()) == {"creative", "analysis", "embedding"}
    assert deleted.status_code == 409


async def test_model_routes_accept_and_protect_fallback_profile(api_env):
    from httpx import ASGITransport, AsyncClient

    def profile(name: str, provider: str, chat_model: str) -> dict:
        return {
            "name": name,
            "provider": provider,
            "base_url": "" if provider == "anthropic" else "https://api.openai.com/v1",
            "api_key": f"key-{name}",
            "chat_models": [chat_model],
            "embedding_models": [] if provider == "anthropic" else ["embed-small"],
        }

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        primary = (await c.post(
            "/api/model-settings/profiles",
            json=profile("Primary", "openai", "gpt-4o"),
        )).json()
        fallback = (await c.post(
            "/api/model-settings/profiles",
            json=profile("Fallback", "anthropic", "claude-sonnet-4-5"),
        )).json()
        routes = await c.put("/api/model-settings/routes", json={
            "creative": {
                "profile_id": primary["id"],
                "model_name": "gpt-4o",
                "fallback_profile_id": fallback["id"],
                "fallback_model_name": "claude-sonnet-4-5",
            },
            "analysis": {"profile_id": primary["id"], "model_name": "gpt-4o"},
            "embedding": {"profile_id": primary["id"], "model_name": "embed-small"},
        })
        deleted = await c.delete(f"/api/model-settings/profiles/{fallback['id']}")

    assert routes.status_code == 200
    assert routes.json()["creative"]["fallback_profile_id"] == fallback["id"]
    assert deleted.status_code == 409


async def test_routed_embedding_profile_cannot_be_changed_to_anthropic(api_env):
    from httpx import ASGITransport, AsyncClient

    profile = {
        "name": "OpenAI",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "chat_models": ["gpt-4o"],
        "embedding_models": ["text-embedding-3-small"],
    }
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        profile_id = (await c.post("/api/model-settings/profiles", json=profile)).json()["id"]
        await c.put(
            "/api/model-settings/routes",
            json={
                "creative": {"profile_id": profile_id, "model_name": "gpt-4o"},
                "analysis": {"profile_id": profile_id, "model_name": "gpt-4o"},
                "embedding": {
                    "profile_id": profile_id,
                    "model_name": "text-embedding-3-small",
                },
            },
        )
        response = await c.put(
            f"/api/model-settings/profiles/{profile_id}",
            json={**profile, "provider": "anthropic", "base_url": ""},
        )

    assert response.status_code == 409
    assert "嵌入" in response.json()["detail"]


async def test_model_settings_write_returns_409_during_graph_stream(api_env):
    from httpx import ASGITransport, AsyncClient

    api_env.app.state.active_streams = 1
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post(
            "/api/model-settings/profiles",
            json={
                "name": "Busy",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "chat_models": ["gpt-4o"],
                "embedding_models": ["text-embedding-3-small"],
            },
        )
    api_env.app.state.active_streams = 0

    assert response.status_code == 409


async def test_model_profile_connection_endpoint_uses_redacted_result(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    async def fake_test(self, profile_id, kind, model_name):
        assert kind == "chat"
        assert model_name == "gpt-4o"
        return {"ok": True, "latency_ms": 12, "message": "连接成功"}

    monkeypatch.setattr("models.resolver.ModelResolver.test_profile", fake_test)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        profile_id = (await c.post(
            "/api/model-settings/profiles",
            json={
                "name": "Test",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "chat_models": ["gpt-4o"],
                "embedding_models": ["text-embedding-3-small"],
            },
        )).json()["id"]
        response = await c.post(
            f"/api/model-settings/profiles/{profile_id}/test",
            json={"kind": "chat", "model_name": "gpt-4o"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "latency_ms": 12, "message": "连接成功"}


async def test_run_rejects_missing_model_configuration_before_stream(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from models.resolver import ModelConfigurationError

    def fail_validation(self):
        raise ModelConfigurationError("未配置创作模型")

    monkeypatch.setattr("api.server.ModelResolver.validate_runtime", fail_validation)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        novel_id = (await c.post(
            "/api/novels",
            json={"title": "配置缺失", "inspiration": "灵感", "total_chapters": 1},
        )).json()["id"]
        response = await c.post(f"/api/novels/{novel_id}/run")

    assert response.status_code == 409
    assert response.json()["detail"] == "未配置创作模型"


async def test_graph_error_event_and_logs_redact_model_secrets(api_env, monkeypatch, caplog):
    from types import SimpleNamespace

    from httpx import ASGITransport, AsyncClient

    class FailingGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={}, next=(), tasks=())

        async def astream(self, payload, config, stream_mode):
            raise RuntimeError(
                "provider failed with test-openai-key Authorization: Bearer header-secret"
            )
            yield

    api_env.app.state.graph = FailingGraph()
    caplog.set_level("ERROR", logger="api")
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        novel_id = (await c.post(
            "/api/novels",
            json={"title": "错误脱敏", "inspiration": "灵感", "total_chapters": 1},
        )).json()["id"]
        response = await c.post(f"/api/novels/{novel_id}/run")

    assert response.status_code == 200
    assert "test-openai-key" not in response.text
    assert "header-secret" not in response.text
    assert "test-openai-key" not in caplog.text
    assert "header-secret" not in caplog.text


async def test_resume_rejects_missing_model_configuration_without_advancing_checkpoint(
    api_env, fake_llm_7, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from models.resolver import ModelConfigurationError

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        novel_id = (await c.post(
            "/api/novels",
            json={"title": "恢复配置缺失", "inspiration": "灵感", "total_chapters": 1},
        )).json()["id"]
        await c.post(f"/api/novels/{novel_id}/run")

        def fail_validation(self):
            raise ModelConfigurationError("未配置分析模型")

        monkeypatch.setattr("api.server.ModelResolver.validate_runtime", fail_validation)
        response = await c.post(f"/api/novels/{novel_id}/resume", json={"feedback": "approve"})
        state = await c.get(f"/api/novels/{novel_id}/state")

    assert response.status_code == 409
    assert state.json()["status"] == "human_review"


async def test_concurrent_run_serializes_and_second_request_gets_409(api_env, fake_llm_7):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "并发测试", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        first, second = await asyncio.gather(
            c.post(f"/api/novels/{nid}/run"),
            c.post(f"/api/novels/{nid}/run"),
        )

    assert sorted([first.status_code, second.status_code]) == [200, 409]


async def test_legacy_incomplete_novel_without_checkpoint_is_read_only(api_env):
    from httpx import ASGITransport, AsyncClient

    api_env.store.create_novel("legacy", "旧作品", total_chapters=2, inspiration="旧灵感")
    api_env.store.save_chapter("legacy", 1, "第一章", "旧正文", status="final")

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post("/api/novels/legacy/run")

    assert response.status_code == 409
    assert "检查点" in response.json()["detail"]


async def test_legacy_completed_novel_without_checkpoint_returns_end(api_env):
    from httpx import ASGITransport, AsyncClient

    api_env.store.create_novel("legacy-done", "旧完本", total_chapters=1)
    api_env.store.save_chapter("legacy-done", 1, "第一章", "旧正文", status="final")

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        response = await c.post("/api/novels/legacy-done/run")

    assert response.status_code == 200
    assert json.loads(response.text)["type"] == "end"
    assert json.loads(response.text)["chapters_done"] == 1


async def test_structured_output_error_preserves_retryable_checkpoint(api_env, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    fake = FakeListChatModel(responses=["无效 YAML", "仍然无效"])
    monkeypatch.setattr("agents.world_builder.get_llm", lambda **kw: fake)

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "错误恢复", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        response = await c.post(f"/api/novels/{nid}/run")

    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["type"] == "error"
    snapshot = await api_env.app.state.graph.aget_state({"configurable": {"thread_id": nid}})
    assert "world_builder" in snapshot.next


async def test_run_with_feedback_revision(api_env, fake_llm_7, monkeypatch):
    """resume 修改意见触发回写,再 approve 定稿(SQLite 只保留终稿)。"""
    from httpx import ASGITransport, AsyncClient

    fake = FakeListChatModel(responses=["重写正文。", "重写润色。", "[]"])
    for mod, attr in [("agents.scene_writer", "get_llm"), ("agents.style_editor", "get_llm"),
                      ("agents.consistency_checker", "get_analyzer_llm")]:
        monkeypatch.setattr(f"{mod}.{attr}", lambda **kw: fake)

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "书", "inspiration": "灵感", "total_chapters": 1, "style": "jin_yong",
        })).json()["id"]
        [line async for line in (await c.post(f"/api/novels/{nid}/run")).aiter_lines()]

        rev = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/resume", json={"feedback": "加强悬念"})).aiter_lines()
            if line.strip()
        ]
        assert rev[-1]["type"] == "interrupt"  # 回写后再次暂停于人工审查

        end = [
            json.loads(line)
            async for line in (await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})).aiter_lines()
            if line.strip()
        ]
        assert end[-1]["type"] == "end"

        chapters = (await c.get(f"/api/novels/{nid}")).json()["chapters"]
        assert len(chapters) == 1
        assert "重写" in chapters[0]["content"]


async def test_scene_scoped_revision_rewrites_selected_scene_and_returns_to_review(
    api_env, fake_llm_7, monkeypatch
):
    """指定 scene_number 时只走局部重写节点,随后重新质检并暂停审查。"""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "局部修订", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")

        invalid = await c.post(
            f"/api/novels/{nid}/resume",
            json={"feedback": "加强冲突", "scene_number": 2},
        )
        assert invalid.status_code == 422
        assert "不存在" in invalid.json()["detail"]

        fake = FakeListChatModel(responses=["局部重写后的场景。", "[]"])
        monkeypatch.setattr("agents.scene_rewriter.get_llm", lambda **kw: fake)
        monkeypatch.setattr("agents.consistency_checker.get_analyzer_llm", lambda **kw: fake)
        revised = [
            json.loads(line)
            for line in (
                await c.post(
                    f"/api/novels/{nid}/resume",
                    json={"feedback": "加强动作冲突", "scene_number": 1},
                )
            ).text.splitlines()
            if line
        ]
        state = (await c.get(f"/api/novels/{nid}/state")).json()

    nodes = [event["node"] for event in revised if event["type"] == "node_done"]
    assert nodes == ["human_review", "scene_rewriter", "consistency_checker"]
    assert revised[-1]["type"] == "interrupt"
    assert state["status"] == "human_review"
    assert state["current_draft"]["content"] == "局部重写后的场景。"
    assert state["current_draft"]["scene_drafts"] == [
        {"scene_number": 1, "content": "局部重写后的场景。"}
    ]


async def test_scene_scoped_revision_requires_nonempty_feedback(api_env, fake_llm_7):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "局部修订校验", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")
        response = await c.post(
            f"/api/novels/{nid}/resume",
            json={"feedback": "", "scene_number": 1},
        )

    assert response.status_code == 422
    assert "修改意见" in response.json()["detail"]


async def test_version_history_diff_and_restore_return_to_review(
    api_env, fake_llm_7, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "版本历史", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")

        fake = FakeListChatModel(responses=["整章重写。", "整章重写润色。", "[]", "[]"])
        monkeypatch.setattr("agents.scene_writer.get_llm", lambda **kw: fake)
        monkeypatch.setattr("agents.style_editor.get_llm", lambda **kw: fake)
        monkeypatch.setattr("agents.consistency_checker.get_analyzer_llm", lambda **kw: fake)
        await c.post(f"/api/novels/{nid}/resume", json={"feedback": "重写整章"})

        versions = (
            await c.get(f"/api/novels/{nid}/chapters/1/versions")
        ).json()
        diff = (
            await c.get(
                f"/api/novels/{nid}/chapters/1/versions/diff",
                params={"from_version": 1, "to_version": 2},
            )
        ).json()
        restored_events = [
            json.loads(line)
            for line in (
                await c.post(
                    f"/api/novels/{nid}/resume",
                    json={"version_number": 1},
                )
            ).text.splitlines()
            if line
        ]
        state = (await c.get(f"/api/novels/{nid}/state")).json()

    assert [item["source"] for item in versions] == ["initial", "revision"]
    assert "初稿润色。" in diff["diff"]
    assert "整章重写润色。" in diff["diff"]
    assert restored_events[-1]["type"] == "interrupt"
    assert state["current_draft"]["content"] == "初稿润色。"
    assert [item["source"] for item in state["versions"]] == [
        "initial",
        "revision",
        "restored",
    ]


async def test_chapter_evaluation_baseline_and_regression_comparison(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "评测测试", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        api_env.store.save_chapter_version(
            nid,
            1,
            source="initial",
            content="第一段。\n\n第二段。\n\n第三段。",
            summary="摘要",
        )
        api_env.store.save_chapter_version(
            nid,
            1,
            source="revision",
            content="重复。\n\n重复。\n\n重复。",
            summary="摘要",
        )
        first = (await c.post(
            f"/api/novels/{nid}/chapters/1/versions/1/evaluations",
            json={"include_judge": False},
        )).json()
        second = (await c.post(
            f"/api/novels/{nid}/chapters/1/versions/2/evaluations",
            json={"include_judge": False},
        )).json()
        baseline = (await c.put(
            f"/api/novels/{nid}/chapters/1/evaluations/{first['id']}/baseline"
        )).json()
        rerun = (await c.post(
            f"/api/novels/{nid}/chapters/1/versions/1/evaluations",
            json={"include_judge": False},
        )).json()
        comparison = (await c.get(
            f"/api/novels/{nid}/chapters/1/evaluations/compare",
            params={"from_version": 1, "to_version": 2},
        )).json()
        evaluations = (await c.get(
            f"/api/novels/{nid}/chapters/1/evaluations"
        )).json()

    assert first["judge_scores"] == {}
    assert second["deterministic_scores"]["repetition_control"] < first["deterministic_scores"]["repetition_control"]
    assert baseline["is_baseline"] is True
    assert rerun["id"] != baseline["id"]
    assert comparison["from_evaluation_id"] == baseline["id"]
    assert comparison["from_version"] == 1
    assert comparison["to_version"] == 2
    assert len(evaluations) == 3


async def test_model_judge_failure_keeps_deterministic_evaluation(
    api_env,
    monkeypatch,
):
    from httpx import ASGITransport, AsyncClient

    class BrokenResolver:
        def __init__(self, **kwargs):
            pass

        def resolve_chat_candidates(self, purpose):
            raise server.ModelConfigurationError("分析模型未配置")

    monkeypatch.setattr(server, "ModelResolver", BrokenResolver)
    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "降级评测", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        api_env.store.save_chapter_version(nid, 1, source="initial", content="正文")
        evaluation = (await c.post(
            f"/api/novels/{nid}/chapters/1/versions/1/evaluations",
            json={"include_judge": True},
        )).json()

    assert evaluation["deterministic_scores"]
    assert evaluation["judge_scores"] == {}
    assert "分析模型未配置" in evaluation["judge_error"]


async def test_sqlite_finalization_failure_returns_retryable_interrupt(
    api_env, fake_llm_7, monkeypatch
):
    """SQLite 定稿失败要通过 NDJSON 暴露原因,修复后可再次 resume。"""
    from httpx import ASGITransport, AsyncClient

    class ToggleStore:
        def __init__(self, delegate):
            self.delegate = delegate
            self.fail = True

        def save_chapter(self, **kwargs):
            if self.fail:
                raise OSError("disk full")
            return self.delegate.save_chapter(**kwargs)

        def save_progress(self, **kwargs):
            return self.delegate.save_progress(**kwargs)

    final_store = ToggleStore(api_env.store)
    monkeypatch.setattr("graph.nodes._store", final_store)

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        nid = (await c.post("/api/novels", json={
            "title": "持久化重试", "inspiration": "灵感", "total_chapters": 1,
        })).json()["id"]
        await c.post(f"/api/novels/{nid}/run")

        failed = [
            json.loads(line)
            for line in (
                await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})
            ).text.splitlines()
            if line
        ]
        assert failed[-1]["type"] == "interrupt"
        assert "disk full" in failed[-1]["persistence_error"]

        final_store.fail = False
        recovered = [
            json.loads(line)
            for line in (
                await c.post(f"/api/novels/{nid}/resume", json={"feedback": "approve"})
            ).text.splitlines()
            if line
        ]

    assert recovered[-1]["type"] == "end"
    assert recovered[-1]["chapters_done"] == 1
