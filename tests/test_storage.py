"""存储层测试:CRUD、路径安全、损坏文件隔离、mutator 原子性。"""

import json

import pytest

from app.core.exceptions import NotFoundError, StorageError
from app.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


async def test_crud_roundtrip(store):
    p = store.create_project("书名", "灵感", "玄幻")
    pid = p["id"]

    got = store.get_project(pid)
    assert got["title"] == "书名"
    assert got["schema_version"] == 1

    updated = await store.update_project(pid, lambda x: x.__setitem__("title", "新书名"))
    assert updated["title"] == "新书名"
    assert store.get_project(pid)["title"] == "新书名"

    assert store.delete_project(pid) is True
    assert store.get_project(pid) is None
    assert store.delete_project(pid) is False


async def test_update_missing_raises_not_found(store):
    """update_project 对不存在的项目抛 NotFoundError(AppError 子类,全局处理器转 404)。"""
    with pytest.raises(NotFoundError):
        await store.update_project("deadbeef1234", lambda x: None)


async def test_update_mutator_exception_not_saved(store):
    p = store.create_project("原题")

    def bad_mutator(x):
        x["title"] = "不该保存"
        raise RuntimeError("mutator 失败")

    with pytest.raises(RuntimeError):
        await store.update_project(p["id"], bad_mutator)
    assert store.get_project(p["id"])["title"] == "原题"


async def test_get_missing_returns_none(store):
    assert store.get_project("deadbeef1234") is None


@pytest.mark.parametrize("bad_pid", ["", "../etc", "a/b", "..", "x" * 65, "恶意字符!"])
async def test_illegal_pid_rejected(store, bad_pid):
    with pytest.raises(NotFoundError):
        store.get_project(bad_pid)
    with pytest.raises(NotFoundError):
        store.delete_project(bad_pid)


async def test_corrupt_file_quarantined(store):
    p = store.create_project("书")
    f = store.root / f"{p['id']}.json"
    f.write_text("{ 损坏的 JSON", encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_project(p["id"])

    # 原文件已移入 corrupt/,不再留在数据目录
    assert not f.exists()
    assert any(store.root.glob("corrupt/*.json"))


async def test_non_dict_payload_quarantined(store):
    p = store.create_project("书")
    f = store.root / f"{p['id']}.json"
    f.write_text(json.dumps(["不是对象"]), encoding="utf-8")
    with pytest.raises(StorageError):
        store.get_project(p["id"])


async def test_list_projects_sorted_and_skips_config(store):
    store.create_project("A")
    store.create_project("B")
    (store.root / "config.json").write_text("{}", encoding="utf-8")
    items = store.list_projects()
    titles = {i["title"] for i in items}
    assert titles == {"A", "B"}  # config.json 不在列表中
    assert all("id" in i and "updated_at" in i for i in items)


async def test_healthcheck_writable(store):
    assert store.healthcheck() is True
