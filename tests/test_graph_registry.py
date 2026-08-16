"""_GraphRegistry LRU 缓存策略测试(内存泄漏修复的回归守护)。

用假图对象注入,精确控制"暂停中"状态,验证:
容量淘汰 / 命中刷新 / 暂停保护 / 全暂停暂缓。
"""

from types import SimpleNamespace

from api.server import _GraphRegistry


class _FakeGraph:
    """get_state 可控的假编译图。"""

    def __init__(self, suspended: bool = False):
        self.suspended = suspended

    def get_state(self, config):
        return SimpleNamespace(next=("human_review",) if self.suspended else ())


def _registry_with(max_size: int, items: dict[str, bool]) -> _GraphRegistry:
    """按 {novel_id: 是否暂停} 构造已达容量的注册表。"""
    reg = _GraphRegistry(max_size=max_size)
    for nid, suspended in items.items():
        reg._items[nid] = {"graph": _FakeGraph(suspended), "lock": None}
    return reg


def test_evicts_oldest_when_over_capacity():
    reg = _registry_with(max_size=2, items={"a": False, "b": False, "c": False})
    assert list(reg._items) == ["a", "b", "c"]

    reg.get_or_create("d")  # 新建触发淘汰:最旧的 a 出局
    assert list(reg._items) == ["b", "c", "d"]


def test_hit_refreshes_lru_position():
    reg = _registry_with(max_size=2, items={"a": False, "b": False})
    reg.get_or_create("a")  # 命中刷新:a 移到最新端

    reg.get_or_create("c")  # 超限淘汰此时最旧的 b
    assert list(reg._items) == ["a", "c"]


def test_suspended_graph_is_protected():
    # a 最旧但暂停中(interrupt 现场),淘汰顺延至 b
    reg = _registry_with(max_size=2, items={"a": True, "b": False, "c": False})
    reg.get_or_create("d")
    assert "a" in reg._items  # 暂停图保留
    assert list(reg._items) == ["a", "c", "d"]  # b 被淘汰


def test_all_suspended_defers_eviction():
    # 全部暂停:暂缓淘汰,不丢任何人工审查现场
    reg = _registry_with(max_size=2, items={"a": True, "b": True, "c": True})
    reg.get_or_create("d")
    assert len(reg._items) == 4  # 接受临时超限

    # 恢复一个后自然收敛:a 仍暂停,b/c/d 中最旧的 c…… 依序淘汰非暂停项
    reg._items["a"]["graph"].suspended = False
    reg.get_or_create("e")
    assert "a" not in reg._items  # a 已可淘汰(最旧且非暂停)


def test_clear_resets_registry():
    reg = _registry_with(max_size=2, items={"a": False, "b": False})
    reg.clear()
    assert len(reg._items) == 0
