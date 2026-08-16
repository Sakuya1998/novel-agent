"""生成任务治理:同一章节互斥写入,防止并行生成造成数据交错。

前端有单页面防重入,但后端必须自我保护:两个并发请求对同一章节
同时 write/continue/polish,会导致两次流式输出相互覆盖或拼接错乱。
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager


class GenerationRegistry:
    """(pid, chapter_index) 级别的非阻塞互斥。"""

    def __init__(self):
        self._active: dict[tuple[str, int], str] = {}  # key -> 描述

    def try_acquire(self, pid: str, index: int, description: str = "") -> bool:
        key = (pid, index)
        if key in self._active:
            return False
        self._active[key] = description
        return True

    def release(self, pid: str, index: int) -> None:
        self._active.pop((pid, index), None)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def snapshot(self) -> list[dict]:
        return [{"pid": pid, "chapter": idx, "task": desc} for (pid, idx), desc in self._active.items()]


@contextmanager
def chapter_generation_lock(
    registry: GenerationRegistry, pid: str, index: int, description: str = ""
) -> Iterator[bool]:
    """获取成功 yield True,获取失败 yield False;离开作用域自动释放。"""
    acquired = registry.try_acquire(pid, index, description)
    try:
        yield acquired
    finally:
        if acquired:
            registry.release(pid, index)


# 单进程全局注册表(多实例部署时由网关/运维层保证单写者)
generation_registry = GenerationRegistry()

# 进程级请求统计(供 /api/stats)。
# 线程模型与无锁依据同 services/llm.py 的 stats:写入仅发生在事件循环线程
# (安全中间件与流式生成器内),读取经 async 路由同线程进行。
metrics = {
    "requests_total": 0,
    "requests_errors": 0,
    "generations_total": 0,
    "started_at": time.time(),
}
