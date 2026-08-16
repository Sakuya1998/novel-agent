"""并发压力测试:验证全局统计计数在并发协程下不丢失、不撕裂。

线程模型说明(见 app/services/llm.py 注释):
- 全部写操作位于事件循环单线程,`+=` 字节码段内无 await 点,协程不会互相打断;
- /api/stats 为 async 路由,读取同样位于事件循环线程,无跨线程访问。
若未来有人把写入挪到线程池或改成多线程,此处的精确断言会立刻失败。
"""
import asyncio

from app.services.llm import LLMClient, stats


async def test_concurrent_streams_count_exactly():
    """并发 20 个 mock 流:streams_total 精确 +20,结束后 active 归零。"""
    before_total = stats["streams_total"]

    async def run_one(i: int):
        client = LLMClient(provider="mock", model="mock")
        chunks = []
        async for c in client.stream("sys", "user", mock_text="测" * 40):
            chunks.append(c)
            await asyncio.sleep(0)  # 让出事件循环,最大化协程交错
        return len(chunks)

    results = await asyncio.gather(*(run_one(i) for i in range(20)))
    assert all(n > 0 for n in results)
    assert stats["streams_total"] == before_total + 20  # 精确无丢失
    assert stats["streams_active"] == 0  # 全部结束


async def test_stats_read_during_streams_is_consistent(client):
    """生成进行中并发读取 stats:不崩溃、不出现负数或撕裂值。"""
    pid = (await client.post("/api/projects", json={"title": "书", "idea": "灵感"})).json()["id"]

    async def generate():
        return await client.post(f"/api/projects/{pid}/generate/premise", json={"idea": "灵感", "genre": "悬疑"})

    gen_task = asyncio.create_task(generate())
    snapshots = []
    while not gen_task.done():
        body = (await client.get("/api/stats")).json()
        snapshots.append(body)
        assert body["llm"]["streams_active"] >= 0
        assert body["llm"]["streams_total"] >= 0
        assert body["requests_total"] >= 0
        await asyncio.sleep(0.005)

    await gen_task
    final = (await client.get("/api/stats")).json()
    # active 在生成结束后必然归零(读数发生在线程收敛后)
    assert final["llm"]["streams_active"] == 0
    assert snapshots  # 确实进行了并发采样
