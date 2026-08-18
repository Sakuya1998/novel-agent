from memory.hierarchical import (
    HIERARCHICAL_MEMORY_SCHEMA_VERSION,
    build_hierarchical_memory,
    format_hierarchical_memory,
    hierarchical_memory_hash,
)


def _chapters(count: int) -> list[dict]:
    return [
        {
            "chapter_number": number,
            "title": f"第{number}章",
            "content": f"第{number}章开头。中段事件。第{number}章结尾。",
            "summary": f"主角完成第{number}阶段行动",
            "events": [f"事件{number}"],
            "characters": ["主角", f"角色{number}"],
            "locations": [f"地点{number}"],
            "extracted_facts": [{"subject": f"线索{number}", "value": f"状态{number}"}],
        }
        for number in range(1, count + 1)
    ]


def test_hierarchical_memory_groups_chapters_into_stable_arcs():
    index = build_hierarchical_memory(_chapters(7), total_chapters=10)

    assert index["schema_version"] == HIERARCHICAL_MEMORY_SCHEMA_VERSION
    assert index["completed_chapters"] == 7
    assert [(item["start_chapter"], item["end_chapter"]) for item in index["arcs"]] == [
        (1, 5),
        (6, 7),
    ]
    assert index["chapters"][5]["facts"][0]["subject"] == "线索6"
    assert "幕2" in index["book_summary"]


def test_hierarchical_memory_format_selects_book_and_chapter_context():
    index = build_hierarchical_memory(_chapters(7), total_chapters=7)

    rendered = format_hierarchical_memory(index, current_chapter=6)

    assert "全书幕级概览" in rendered
    assert "第6章" in rendered
    assert "主角完成第6阶段行动" in rendered
    assert len(hierarchical_memory_hash(index)) == 64
    changed = build_hierarchical_memory(
        [*_chapters(6), {**_chapters(7)[-1], "summary": "返修后的第七阶段"}],
        total_chapters=7,
    )
    assert hierarchical_memory_hash(changed) != hierarchical_memory_hash(index)
