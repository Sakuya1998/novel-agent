"""SQLite 结构化存储测试。"""


def test_novel_crud(store):
    created = store.create_novel("n1", "雾中剑", genre="武侠", style="gu_long", total_chapters=3, inspiration="灵感")
    assert created["id"] == "n1"

    got = store.get_novel("n1")
    assert got["title"] == "雾中剑"
    assert got["inspiration"] == "灵感"

    assert store.get_novel("missing") is None
    assert [n["id"] for n in store.list_novels()] == ["n1"]


def test_chapter_upsert_idempotent(store):
    store.create_novel("n1", "书")
    rid1 = store.save_chapter("n1", 1, "雾起", "第一章内容", "摘要", "draft")
    rid2 = store.save_chapter("n1", 1, "雾起(改)", "第一章内容改", "摘要改", "final")
    assert rid1 == rid2  # 同 novel+chapter 幂等更新

    ch = store.get_chapter("n1", 1)
    assert ch["title"] == "雾起(改)"
    assert ch["status"] == "final"
    assert ch["word_count"] == len("第一章内容改")

    chapters = store.get_all_chapters("n1")
    assert len(chapters) == 1


def test_chapter_isolation_between_novels(store):
    store.create_novel("a", "甲书")
    store.create_novel("b", "乙书")
    store.save_chapter("a", 1, "甲一章", "内容")
    store.save_chapter("b", 1, "乙一章", "内容")
    assert store.get_chapter("a", 1)["title"] == "甲一章"
    assert len(store.get_all_chapters("b")) == 1


def test_progress_roundtrip(store):
    store.create_novel("n1", "书")
    store.save_progress("n1", current_chapter=2, current_phase="writing", state={"chapters": ["c1"]})

    p = store.get_progress("n1")
    assert p["current_chapter"] == 2
    assert p["current_phase"] == "writing"
    assert p["state"] == {"chapters": ["c1"]}

    # 更新覆盖
    store.save_progress("n1", current_chapter=3, current_phase="style_editing")
    assert store.get_progress("n1")["current_chapter"] == 3
