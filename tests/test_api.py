"""API 集成测试:CRUD、校验、流式生成(mock)、鉴权、限流、互斥、健康检查。"""

import asyncio
import json

import pytest_asyncio
from conftest import make_app
from httpx import ASGITransport, AsyncClient


def parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def deltas_text(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "delta")


# ---------------- 健康检查 ----------------
async def test_healthz_readyz(client):
    assert (await client.get("/healthz")).json()["status"] == "ok"
    ready = (await client.get("/readyz")).json()
    assert ready["status"] == "ok"
    assert ready["data_dir_writable"] is True


# ---------------- 设置 ----------------
async def test_settings_roundtrip_and_masking(client):
    resp = await client.put(
        "/api/settings",
        json={
            "provider": "openai",
            "model": "m",
            "base_url": "https://x/v1",
            "api_key": "sk-abcdefgh12345678",
            "temperature": 0.8,
            "chapter_words": 2500,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_key"].startswith("***")  # 脱敏
    assert body["api_key_set"] is True

    # 原样回传脱敏值,不应覆盖真实 Key
    get1 = (await client.get("/api/settings")).json()
    await client.put("/api/settings", json={"provider": "openai", "model": "m", "api_key": get1["api_key"]})
    get2 = (await client.get("/api/settings")).json()
    assert get1["api_key"] == get2["api_key"]  # 掩码不变说明真实 Key 未被覆盖


async def test_settings_validation(client):
    resp = await client.put("/api/settings", json={"provider": "invalid", "model": "m"})
    assert resp.status_code == 422
    resp = await client.put("/api/settings", json={"provider": "openai", "model": "m", "temperature": 99})
    assert resp.status_code == 422


# ---------------- 项目 CRUD ----------------
async def test_project_crud(client):
    resp = await client.post("/api/projects", json={"title": "新书", "idea": "灵感", "genre": "科幻"})
    assert resp.status_code == 200
    pid = resp.json()["id"]

    assert (await client.get(f"/api/projects/{pid}")).json()["title"] == "新书"

    resp = await client.patch(f"/api/projects/{pid}", json={"title": "改题"})
    assert resp.json()["title"] == "改题"

    listed = (await client.get("/api/projects")).json()
    assert any(p["id"] == pid for p in listed)

    assert (await client.delete(f"/api/projects/{pid}")).status_code == 200
    assert (await client.get(f"/api/projects/{pid}")).status_code == 404


async def test_project_validation(client):
    assert (await client.post("/api/projects", json={"title": ""})).status_code == 422
    assert (await client.post("/api/projects", json={"title": "x" * 201})).status_code == 422
    assert (await client.post("/api/projects", json={})).status_code == 422


async def test_project_not_found(client):
    assert (await client.get("/api/projects/nonexistent00")).status_code == 404
    # PATCH 路径同样走 update_project 的 NotFoundError → 全局处理器 → 404(而非 KeyError 兜底 500)
    assert (await client.patch("/api/projects/nonexistent00", json={"title": "x"})).status_code == 404


async def test_illegal_pid_is_404_not_500(client):
    assert (await client.get("/api/projects/../etc/passwd")).status_code in (404, 400)


# ---------------- 生成:premise / characters / outline(mock 流式) ----------------
async def test_generate_premise_stream(client):
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]
    resp = await client.post(f"/api/projects/{pid}/generate/premise", json={"idea": "灵感", "genre": "悬疑"})
    assert resp.status_code == 200
    events = parse_ndjson(resp.text)
    assert deltas_text(events)  # 有增量内容
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["project"]["premise"]  # 已保存


async def test_generate_characters_and_outline(client):
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]

    resp = await client.post(f"/api/projects/{pid}/generate/characters", json={"count": 3})
    events = parse_ndjson(resp.text)
    done = [e for e in events if e["type"] == "done"]
    assert done and len(done[0]["project"]["characters"]) == 3

    resp = await client.post(f"/api/projects/{pid}/generate/outline", json={"num_chapters": 4})
    events = parse_ndjson(resp.text)
    done = [e for e in events if e["type"] == "done"]
    assert done and len(done[0]["project"]["outline"]) == 4


async def test_generate_validation(client):
    pid = (await client.post("/api/projects", json={"title": "书"})).json()["id"]
    assert (await client.post(f"/api/projects/{pid}/generate/characters", json={"count": 0})).status_code == 422
    assert (await client.post(f"/api/projects/{pid}/generate/outline", json={"num_chapters": 999})).status_code == 422


# ---------------- 章节生成 ----------------
async def test_chapter_write_flow(client):
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]
    # 先造大纲,写作时应取大纲标题
    await client.post(f"/api/projects/{pid}/generate/outline", json={"num_chapters": 4})

    resp = await client.post(f"/api/projects/{pid}/chapters/1/write", json={"instruction": ""})
    events = parse_ndjson(resp.text)
    assert not [e for e in events if e["type"] == "error"], events
    done = [e for e in events if e["type"] == "done"][0]
    ch = done["project"]["chapters"][0]
    assert ch["index"] == 1
    assert ch["content"]
    assert ch["summary"]  # 自动摘要
    assert any(e["type"] == "status" and "摘要" in e["text"] for e in events)


async def test_chapter_continue_appends(client):
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]
    await client.post(f"/api/projects/{pid}/chapters/1/write", json={"instruction": ""})
    first = (await client.get(f"/api/projects/{pid}")).json()["chapters"][0]["content"]

    resp = await client.post(f"/api/projects/{pid}/chapters/1/continue", json={"instruction": ""})
    events = parse_ndjson(resp.text)
    assert not [e for e in events if e["type"] == "error"], events
    second = [e for e in events if e["type"] == "done"][0]["project"]["chapters"][0]["content"]
    assert len(second) > len(first)
    assert second.startswith(first)  # 无缝拼接


async def test_polish_without_content_errors(client):
    pid = (await client.post("/api/projects", json={"title": "书"})).json()["id"]
    resp = await client.post(f"/api/projects/{pid}/chapters/1/polish", json={"instruction": ""})
    events = parse_ndjson(resp.text)
    errors = [e for e in events if e["type"] == "error"]
    assert errors and "正文" in errors[0]["message"]


async def test_same_chapter_concurrent_generation_rejected(client):
    """互斥:同一章节并行生成,后到的请求收到错误事件。"""
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]

    async def one():
        return await client.post(f"/api/projects/{pid}/chapters/1/write", json={"instruction": ""})

    r1, r2 = await asyncio.gather(one(), one())
    ev1 = parse_ndjson(r1.text)
    ev2 = parse_ndjson(r2.text)
    rejected = [e for e in ev1 + ev2 if e["type"] == "error" and "正在生成中" in e["message"]]
    done = [e for e in ev1 + ev2 if e["type"] == "done"]
    assert rejected and len(done) == 1  # 恰好一个被拒、一个成功


async def test_chapter_crud_and_summary(client):
    pid = (await client.post("/api/projects", json={"title": "书"})).json()["id"]

    # 新增章节
    resp = await client.post(f"/api/projects/{pid}/chapters", json={"title": ""})
    assert resp.json()["chapters"][0]["index"] == 1

    # 写入正文
    await client.put(f"/api/projects/{pid}/chapters/1", json={"title": "题", "content": "正文内容很长。"})
    # 生成摘要
    resp = await client.post(f"/api/projects/{pid}/chapters/1/summary")
    assert resp.status_code == 200
    assert resp.json()["chapters"][0]["summary"]

    # 无正文章节摘要 → 404(本章还没有正文)
    await client.post(f"/api/projects/{pid}/chapters", json={"title": ""})
    resp = await client.post(f"/api/projects/{pid}/chapters/2/summary")
    assert resp.status_code == 404

    # 删除
    resp = await client.delete(f"/api/projects/{pid}/chapters/1")
    assert all(c["index"] != 1 for c in resp.json()["chapters"])


# ---------------- 鉴权 ----------------
@pytest_asyncio.fixture
async def authed_client(tmp_path):
    app = make_app(tmp_path, auth_key="secret-key-123")
    app.state.runtime_settings.save({"provider": "mock", "model": "mock"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_auth_required(authed_client):
    assert (await authed_client.get("/api/projects")).status_code == 401
    assert (await authed_client.get("/healthz")).status_code == 200  # 健康探针免鉴权

    wrong = await authed_client.get("/api/projects", headers={"X-API-Key": "bad"})
    assert wrong.status_code == 401

    ok = await authed_client.get("/api/projects", headers={"X-API-Key": "secret-key-123"})
    assert ok.status_code == 200


# ---------------- 限流 ----------------
@pytest_asyncio.fixture
async def limited_client(tmp_path):
    app = make_app(tmp_path, rate_limit="3/60")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_rate_limit(limited_client):
    codes = [(await limited_client.get("/api/projects")).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429 and codes[4] == 429
    assert (await limited_client.get("/healthz")).status_code == 200  # 非接口路径不限流


# ---------------- 请求体大小限制 ----------------
async def test_oversized_body_rejected(tmp_path):
    from conftest import make_app as _make

    app = _make(tmp_path, max_body_mb=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        big = "x" * (1024 * 1024 + 100)  # > 1MB
        resp = await c.post(
            "/api/projects",
            content=json.dumps({"title": "t", "idea": big}).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413
        assert "上限" in resp.json()["detail"]


async def test_normal_body_within_limit(client):
    resp = await client.post("/api/projects", json={"title": "正常", "idea": "短"})
    assert resp.status_code == 200


# ---------------- 运行统计 ----------------
async def test_stats_endpoint(client):
    await client.get("/api/projects")
    resp = await client.get("/api/stats")
    body = resp.json()
    assert body["requests_total"] >= 1
    assert body["llm"]["streams_total"] >= 0


async def test_stats_counts_mock_generations(client):
    """mock 生成也计入 LLM 统计,保证指标口径一致。"""
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]
    await client.post(f"/api/projects/{pid}/generate/premise", json={"idea": "灵感", "genre": "悬疑"})

    body = (await client.get("/api/stats")).json()
    assert body["llm"]["streams_total"] >= 1  # 正文 + 摘要
    assert body["generations_total"] >= 1
