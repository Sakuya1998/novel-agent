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
def fake_llm_6(monkeypatch):
    """一轮完整章节的固定回复。"""
    fake = FakeListChatModel(
        responses=[
            "```yaml\n世界观名称: 测试\n```",
            "- name: 林寒\n  role: 主角\n",
            "- chapter: 1\n  title: 雾起\n  estimated_words: 100\n",
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
        ("agents.scene_writer", "get_llm"),
        ("agents.style_editor", "get_llm"),
        ("agents.consistency_checker", "get_analyzer_llm"),
    ]:
        monkeypatch.setattr(f"{mod}.{attr}", lambda **kw: fake)
    return fake


async def test_healthz(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        assert (await c.get("/healthz")).json() == {"status": "ok"}


async def test_novel_crud_flow(api_env):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=api_env.app), base_url="http://t") as c:
        created = (await c.post("/api/novels", json={
            "title": "雾中剑", "genre": "武侠", "inspiration": "失忆剑客",
            "total_chapters": 1, "style": "gu_long",
        })).json()
        nid = created["id"]
        assert created["inspiration"] == "失忆剑客"

        assert len((await c.get("/api/novels")).json()) == 1
        detail = (await c.get(f"/api/novels/{nid}")).json()
        assert detail["title"] == "雾中剑"

        assert (await c.get("/api/novels/none")).status_code == 404
        assert (await c.post("/api/novels/{none}/run".replace("{none}", "none"))).status_code == 404


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


async def test_run_interrupt_resume_flow(api_env, fake_llm_6):
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
                         "scene_writer", "style_editor", "consistency_checker"]

        interrupt_ev = lines[-1]
        assert interrupt_ev["type"] == "interrupt"
        assert interrupt_ev["title"] == "雾起"

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


async def test_state_for_human_review_contains_draft(api_env, fake_llm_6):
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
    assert state["next"] == ["human_review"]


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
    api_env, fake_llm_6, monkeypatch
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


async def test_concurrent_run_serializes_and_second_request_gets_409(api_env, fake_llm_6):
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


async def test_run_with_feedback_revision(api_env, fake_llm_6, monkeypatch):
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


async def test_sqlite_finalization_failure_returns_retryable_interrupt(
    api_env, fake_llm_6, monkeypatch
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
