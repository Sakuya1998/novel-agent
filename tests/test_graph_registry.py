"""API 作品级弱引用锁测试。"""

import gc

from api.server import _novel_locks, get_novel_lock


def test_live_novel_lock_is_reused():
    _novel_locks.clear()
    first = get_novel_lock("novel-a")
    second = get_novel_lock("novel-a")
    assert first is second


def test_unused_novel_lock_can_be_collected():
    _novel_locks.clear()
    lock = get_novel_lock("novel-a")
    assert "novel-a" in _novel_locks

    del lock
    gc.collect()

    assert "novel-a" not in _novel_locks
