"""Agent 核心逻辑测试:JSON 解析、规范化、上下文构建、章节字段。"""

import pytest

from app.api.routes_chapters import _chapter_fields, _upsert_chapter
from app.services.agent import (
    MOCK_CHARACTERS,
    MOCK_OUTLINE,
    NovelAgent,
    extract_json_array,
    normalize_characters,
    normalize_outline,
)


def test_extract_json_array_plain():
    data = extract_json_array('[{"a": 1}]')
    assert data == [{"a": 1}]


def test_extract_json_array_with_code_fence():
    text = '```json\n[{"a": 1}, {"b": 2}]\n```'
    assert extract_json_array(text) == [{"a": 1}, {"b": 2}]


def test_extract_json_array_with_surrounding_text():
    text = "以下是角色卡:\n[{'name': '甲'}] 以上。".replace("'", '"')
    assert extract_json_array(text) == [{"name": "甲"}]


def test_extract_json_array_invalid():
    with pytest.raises(ValueError):
        extract_json_array("没有数组")
    with pytest.raises(ValueError):
        extract_json_array('{"obj": 1}')


def test_normalize_characters_filters_and_fields():
    raw = [
        {"name": "  沈青梧  ", "role": "主角"},
        {"no_name": True},  # 无名字,过滤
        "不是对象",  # 过滤
    ]
    out = normalize_characters(raw)
    assert len(out) == 1
    assert out[0]["name"] == "沈青梧"
    assert set(out[0].keys()) == {
        "name",
        "role",
        "appearance",
        "personality",
        "background",
        "goal",
        "arc",
        "relationships",
    }


def test_normalize_characters_rejects_empty():
    with pytest.raises(ValueError):
        normalize_characters([{"name": ""}, 42])


def test_normalize_outline_defaults_and_truncation():
    raw = [
        {"title": "", "summary": "只有概要", "index": "bad"},  # index 回退为 1,title 回退
        {"title": "第二章"},  # 无 summary 保留 title
        {"neither": 1},  # title/summary 均空 → 过滤
    ]
    out = normalize_outline(raw)
    assert len(out) == 2
    assert out[0]["index"] == 1
    assert out[0]["title"] == "第1章"
    assert out[1]["index"] == 2


def test_normalize_outline_rejects_empty():
    with pytest.raises(ValueError):
        normalize_outline([])


def test_mock_payloads_parseable():
    """mock 数据本身必须是可解析的,保证离线演示链路可用。"""
    assert len(normalize_characters(extract_json_array(MOCK_CHARACTERS))) == 3
    assert len(normalize_outline(extract_json_array(MOCK_OUTLINE))) == 4


# ---------------- 上下文构建 ----------------
def _proj_with_chapters(n: int) -> dict:
    chapters = []
    for i in range(1, n + 1):
        chapters.append(
            {
                "index": i,
                "title": f"第{i}章",
                "content": f"第{i}章正文" + "尾" * 500 if i == n else f"第{i}章正文",
                "summary": f"摘要{i}" if i != n else "",  # 最后一章无摘要 → 回退正文结尾
            }
        )
    return {"premise": "设定", "characters": [], "outline": [], "chapters": chapters}


def test_prev_context_keeps_last_six():
    agent = NovelAgent({"provider": "mock", "model": "mock"})
    ctx = agent._prev_context(_proj_with_chapters(10), 11)
    lines = ctx.splitlines()
    assert len(lines) == 6
    assert "摘要5" in lines[0]
    assert "第10章" in lines[-1]
    assert "正文结尾" in lines[-1]  # 无摘要回退


def test_prev_context_empty_for_first_chapter():
    agent = NovelAgent({"provider": "mock", "model": "mock"})
    assert agent._prev_context(_proj_with_chapters(3), 1) == ""


# ---------------- 章节字段 ----------------
def test_chapter_fields_write_replaces():
    p = {
        "outline": [{"index": 1, "title": "开篇", "summary": "s", "key_events": "e"}],
        "chapters": [{"index": 1, "title": "旧", "content": "旧正文", "summary": ""}],
    }
    fields = _chapter_fields(p, 1, "write", "新正文", "")
    assert fields["title"] == "开篇"  # 取大纲标题
    assert fields["content"] == "新正文"


def test_chapter_fields_continue_appends():
    p = {"outline": [], "chapters": [{"index": 1, "title": "旧", "content": "已有正文。", "summary": ""}]}
    fields = _chapter_fields(p, 1, "continue", "接续内容", "")
    assert fields["content"].startswith("已有正文。")
    assert fields["content"].endswith("接续内容")


def test_upsert_chapter_creates_and_updates():
    p = {"chapters": [], "outline": []}
    _upsert_chapter(p, 1, title="第一章", content="abc")
    assert p["chapters"][0]["title"] == "第一章"
    _upsert_chapter(p, 1, content="xyz")
    assert len(p["chapters"]) == 1
    assert p["chapters"][0]["content"] == "xyz"
