"""可重建的分层长篇记忆索引。

索引只依赖已经批准的章节摘要与事实，不承担 Canon 的权威语义；它的职责是
在章节数量增长后提供稳定的全书、幕和章节级上下文，避免 Prompt 只能看到最近几章。
"""

import hashlib
import json
from typing import Any

HIERARCHICAL_MEMORY_SCHEMA_VERSION = "book-memory-v1"
ARC_SIZE = 5


def _chapter_number(chapter: dict[str, Any]) -> int:
    return int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)


def _chapter_leaf(chapter: dict[str, Any]) -> dict[str, Any]:
    number = _chapter_number(chapter)
    digest = chapter.get("digest") if isinstance(chapter.get("digest"), dict) else {}
    summary = str(chapter.get("summary") or digest.get("summary") or "").strip()
    content = str(chapter.get("content", "")).strip()
    return {
        "chapter": number,
        "title": str(chapter.get("title", ""))[:200],
        "summary": summary[:500],
        "events": [str(item)[:300] for item in (chapter.get("events") or digest.get("events") or [])[:12]],
        "characters": [
            str(item)[:120]
            for item in (chapter.get("characters") or digest.get("characters") or [])[:16]
        ],
        "locations": [
            str(item)[:120]
            for item in (chapter.get("locations") or digest.get("locations") or [])[:12]
        ],
        "facts": [
            {
                "subject": str(item.get("subject", ""))[:160],
                "value": str(item.get("value", ""))[:300],
            }
            for item in (chapter.get("extracted_facts") or digest.get("extracted_facts") or [])[:12]
            if isinstance(item, dict)
        ],
        "opening": content[:180],
        "closing": content[-180:] if content else "",
    }


def build_hierarchical_memory(
    chapters: list[dict[str, Any]],
    *,
    total_chapters: int = 0,
) -> dict[str, Any]:
    """从终稿章节构建章节、幕和全书三级索引。"""
    leaves = [
        _chapter_leaf(item)
        for item in sorted(chapters, key=_chapter_number)
        if _chapter_number(item) > 0
    ]
    arcs: list[dict[str, Any]] = []
    for offset in range(0, len(leaves), ARC_SIZE):
        group = leaves[offset : offset + ARC_SIZE]
        start = group[0]["chapter"]
        end = group[-1]["chapter"]
        summaries = [
            f"第{item['chapter']}章《{item['title']}》: {item['summary']}"
            for item in group
            if item["summary"]
        ]
        events = [event for item in group for event in item["events"]]
        characters = sorted({name for item in group for name in item["characters"]})
        locations = sorted({name for item in group for name in item["locations"]})
        arcs.append({
            "arc": len(arcs) + 1,
            "start_chapter": start,
            "end_chapter": end,
            "summary": " ".join(summaries)[:1800],
            "events": events[:24],
            "characters": characters[:24],
            "locations": locations[:16],
        })

    book_summary = "\n".join(
        f"幕{arc['arc']}（第{arc['start_chapter']}-{arc['end_chapter']}章）：{arc['summary']}"
        for arc in arcs
    )[:6000]
    return {
        "schema_version": HIERARCHICAL_MEMORY_SCHEMA_VERSION,
        "arc_size": ARC_SIZE,
        "completed_chapters": len(leaves),
        "total_chapters": int(total_chapters or len(leaves)),
        "book_summary": book_summary,
        "arcs": arcs,
        "chapters": leaves,
    }


def hierarchical_memory_hash(index: dict[str, Any]) -> str:
    payload = json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_hierarchical_memory(
    index: dict[str, Any] | None,
    *,
    current_chapter: int = 0,
    max_chars: int = 4500,
) -> str:
    """按当前章节选择相邻幕和局部章节叶节点，生成 Prompt 文本。"""
    if not isinstance(index, dict) or not index.get("chapters"):
        return "暂无分层全书记忆。"
    arcs = index.get("arcs") or []
    selected_arcs = [
        arc for arc in arcs
        if current_chapter <= 0
        or int(arc.get("end_chapter", 0) or 0) >= current_chapter - ARC_SIZE
    ]
    leaves = [
        leaf for leaf in index.get("chapters") or []
        if current_chapter <= 0
        or abs(int(leaf.get("chapter", 0) or 0) - current_chapter) <= ARC_SIZE
    ]
    parts = [
        "## 全书幕级概览\n" + "\n".join(
            f"- 幕{arc.get('arc')}: {arc.get('summary', '')}"
            for arc in selected_arcs
        ),
        "## 章节级锚点\n" + "\n".join(
            f"- 第{leaf.get('chapter')}章《{leaf.get('title', '')}》: {leaf.get('summary', '')}"
            for leaf in leaves
            if leaf.get("summary")
        ),
    ]
    return "\n\n".join(parts)[:max_chars]
