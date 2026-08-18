"""结构化小说 Canon:世界事实、角色状态与章节时间线。"""

import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import yaml

CANON_VERSION = 3
_WORLD_FACT_LIMIT = 80
_FACT_VALUE_LIMIT = 300
_AUDIT_LIMIT = 200
_CHARACTER_EDITABLE_FIELDS = {
    "role",
    "personality",
    "relationships",
    "speech_pattern",
    "behavior",
    "arc",
}
_THREAD_ACTIONS = {"setup", "develop", "resolve"}
_THREAD_STATUSES = {"planned", "open", "resolved", "abandoned"}
_THREAD_PRIORITIES = {"major", "minor"}
_THREAD_ACTION_ALIASES = {
    "setup": "setup",
    "plant": "setup",
    "introduce": "setup",
    "埋设": "setup",
    "设置": "setup",
    "引入": "setup",
    "develop": "develop",
    "advance": "develop",
    "推进": "develop",
    "发展": "develop",
    "加深": "develop",
    "提醒": "develop",
    "resolve": "resolve",
    "payoff": "resolve",
    "回收": "resolve",
    "揭示": "resolve",
    "解决": "resolve",
}


def empty_canon() -> dict[str, Any]:
    """返回可安全写入 LangGraph 检查点的空 Canon。"""
    return {
        "version": CANON_VERSION,
        "world_facts": [],
        "characters": {},
        "aliases": {},
        "timeline": [],
        "facts": [],
        "narrative_threads": [],
        "audit": [],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _world_fact_id(path: str) -> str:
    digest = hashlib.sha1(path.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"world:{digest}"


def _thread_id(title: str) -> str:
    normalized = " ".join(title.casefold().split())
    digest = hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"thread:{digest}"


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _thread_action(value: Any, default: str = "develop") -> str:
    raw = str(value or "").strip().casefold()
    return _THREAD_ACTION_ALIASES.get(raw, default)


def _legacy_foreshadowing_beat(value: Any, chapter: int) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return _normalize_narrative_beat(value, chapter)
    text = str(value or "").strip()
    if not text:
        return None
    match = re.match(r"^(埋设|设置|引入|推进|发展|加深|提醒|回收|揭示|解决)\s*[:：-]?\s*(.+)$", text)
    if match:
        action = _thread_action(match.group(1))
        title = match.group(2).strip()
    else:
        action = "develop"
        title = text
    return {
        "thread": title,
        "action": action,
        "description": text,
        "priority": "minor",
        "chapter": chapter,
    }


def _normalize_narrative_beat(value: Any, chapter: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return _legacy_foreshadowing_beat(value, chapter)
    title = str(value.get("thread", value.get("title", ""))).strip()
    if not title:
        return None
    action = _thread_action(value.get("action"))
    priority = str(value.get("priority", "minor")).strip().casefold()
    if priority not in _THREAD_PRIORITIES:
        priority = "minor"
    normalized = {
        "thread": title,
        "action": action,
        "description": str(value.get("description", title)).strip()[:500] or title,
        "priority": priority,
        "chapter": chapter,
    }
    due_chapter = _positive_int(value.get("due_chapter"))
    if due_chapter:
        normalized["due_chapter"] = due_chapter
    kind = str(value.get("kind", "foreshadowing")).strip()
    if kind:
        normalized["kind"] = kind[:80]
    beat_id = str(value.get("beat_id", value.get("id", ""))).strip()
    if beat_id:
        normalized["beat_id"] = beat_id
    scene_number = _positive_int(value.get("scene_number"))
    if scene_number:
        normalized["scene_number"] = scene_number
    return normalized


def narrative_beats_from_chapter(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    """读取新旧章节格式中的叙事 beat，并返回稳定结构。"""
    number = int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)
    raw_beats = chapter.get("narrative_beats")
    if raw_beats in (None, ""):
        raw_beats = chapter.get("foreshadowing") or []
    if isinstance(raw_beats, (str, dict)):
        raw_beats = [raw_beats]
    beats = [
        beat
        for item in (raw_beats if isinstance(raw_beats, list) else [])
        if (beat := _normalize_narrative_beat(item, number)) is not None
    ]
    return beats


def _build_narrative_threads(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threads: dict[str, dict[str, Any]] = {}
    for chapter in sorted(
        chapters,
        key=lambda item: int(item.get("chapter_number", item.get("chapter", 0)) or 0),
    ):
        number = int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)
        for index, beat in enumerate(narrative_beats_from_chapter(chapter), start=1):
            title = beat["thread"]
            thread_id = _thread_id(title)
            thread = threads.setdefault(thread_id, {
                "id": thread_id,
                "title": title,
                "description": beat["description"],
                "kind": beat.get("kind", "foreshadowing"),
                "priority": beat.get("priority", "minor"),
                "status": "planned",
                "introduced_chapter": number,
                "due_chapter": None,
                "resolved_chapter": None,
                "source": "outline",
                "beats": [],
            })
            if beat.get("priority") == "major":
                thread["priority"] = "major"
            if beat["action"] == "setup":
                thread["introduced_chapter"] = min(
                    int(thread.get("introduced_chapter") or number),
                    number,
                )
            due_chapter = _positive_int(beat.get("due_chapter"))
            if beat["action"] == "resolve":
                due_chapter = number
            if due_chapter:
                current_due = _positive_int(thread.get("due_chapter"))
                thread["due_chapter"] = min(current_due, due_chapter) if current_due else due_chapter
            thread["beats"].append({
                "id": f"{thread_id}:beat:{number}:{beat['action']}:{index}",
                "chapter": number,
                "action": beat["action"],
                "description": beat["description"],
                "status": "planned",
            })
    return sorted(
        threads.values(),
        key=lambda item: (int(item.get("introduced_chapter", 0) or 0), str(item.get("title", ""))),
    )


def narrative_beats_for_chapter(
    canon: dict[str, Any] | None,
    chapter_number: int,
) -> list[dict[str, Any]]:
    """从 Canon 读取指定章节应执行的全部叙事 beat。"""
    beats: list[dict[str, Any]] = []
    for thread in (canon or {}).get("narrative_threads") or []:
        if thread.get("status") in {"resolved", "abandoned"}:
            continue
        for beat in thread.get("beats") or []:
            if int(beat.get("chapter", 0) or 0) != chapter_number:
                continue
            item = {
                "beat_id": beat.get("id"),
                "thread": thread.get("title", ""),
                "action": beat.get("action", "develop"),
                "description": beat.get("description", thread.get("description", "")),
                "kind": thread.get("kind", "foreshadowing"),
                "priority": thread.get("priority", "minor"),
            }
            if thread.get("due_chapter"):
                item["due_chapter"] = thread["due_chapter"]
            if beat.get("scene_number"):
                item["scene_number"] = beat["scene_number"]
            beats.append(item)
    return beats


def _plain_yaml(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _world_mapping(world_bible: str) -> dict[str, Any]:
    if not world_bible.strip():
        return {}
    try:
        parsed = yaml.safe_load(_plain_yaml(world_bible))
    except yaml.YAMLError:
        return {}
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        parsed = parsed[0]
    return parsed if isinstance(parsed, dict) else {}


def _flatten_world(value: Any, path: str = "") -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            facts.extend(_flatten_world(child, child_path))
            if len(facts) >= _WORLD_FACT_LIMIT:
                break
        return facts[:_WORLD_FACT_LIMIT]
    if isinstance(value, list):
        scalar_values = [str(item) for item in value if not isinstance(item, (dict, list))]
        if scalar_values:
            facts.append({
                "id": _world_fact_id(path or "world"),
                "path": path or "world",
                "value": ", ".join(scalar_values)[:_FACT_VALUE_LIMIT],
                "source": "world_builder",
                "status": "active",
            })
        for index, child in enumerate(item for item in value if isinstance(item, (dict, list))):
            facts.extend(_flatten_world(child, f"{path}[{index}]"))
            if len(facts) >= _WORLD_FACT_LIMIT:
                break
        return facts[:_WORLD_FACT_LIMIT]
    if value is not None and str(value).strip():
        facts.append({
            "id": _world_fact_id(path or "world"),
            "path": path or "world",
            "value": str(value).strip()[:_FACT_VALUE_LIMIT],
            "source": "world_builder",
            "status": "active",
        })
    return facts


def _character_record(character: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(character.get("name", "")).strip(),
        "role": character.get("role", ""),
        "personality": character.get("personality", ""),
        "relationships": character.get("relationships", []),
        "speech_pattern": character.get("speech_pattern", ""),
        "behavior": character.get("behavior", ""),
        "arc": character.get("arc", ""),
        "last_seen_chapter": 0,
        "appearances": [],
    }


def _timeline_entry(chapter: dict[str, Any], *, status: str) -> dict[str, Any]:
    number = int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)
    entry: dict[str, Any] = {
        "chapter": number,
        "title": str(chapter.get("title", "")),
        "summary": str(chapter.get("summary", ""))[:500],
        "status": status,
    }
    for key in ("time_days", "emotion", "characters", "locations", "events", "foreshadowing"):
        if key in chapter and chapter[key] not in (None, "", []):
            entry[key] = deepcopy(chapter[key])
    return entry


def build_canon(
    *,
    world_bible: str,
    characters: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    chapters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """从现有创作状态构建 Canon,也用于旧检查点的无损升级。"""
    canon = empty_canon()
    canon["world_facts"] = _flatten_world(_world_mapping(world_bible))
    canon["characters"] = {
        record["name"]: record
        for item in characters
        if (record := _character_record(item))["name"]
    }
    canon["timeline"] = [
        _timeline_entry(item, status="planned")
        for item in outline
        if int(item.get("chapter", item.get("chapter_number", 0)) or 0) > 0
    ]
    canon["narrative_threads"] = _build_narrative_threads(outline)
    for chapter in chapters or []:
        canon = record_final_chapter(canon, chapter)
    return canon


def ensure_canon(
    canon: dict[str, Any] | None,
    *,
    world_bible: str,
    characters: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    chapters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """返回已规范化 Canon;缺失或旧版本时从权威状态重建。"""
    has_authoritative_content = bool(world_bible.strip() or characters or outline or chapters)
    has_canon_content = isinstance(canon, dict) and any(
        canon.get(key)
        for key in ("world_facts", "characters", "timeline", "facts", "narrative_threads")
    )
    if not isinstance(canon, dict) or (has_authoritative_content and not has_canon_content):
        return build_canon(
            world_bible=world_bible,
            characters=characters,
            outline=outline,
            chapters=chapters,
        )
    normalized = empty_canon()
    for key in normalized:
        if key != "version" and key in canon:
            normalized[key] = deepcopy(canon[key])
    for item in normalized["world_facts"]:
        item.setdefault("id", _world_fact_id(str(item.get("path", "world"))))
        item.setdefault("status", "active")
    for item in normalized["facts"]:
        item.setdefault("status", "active")
    if not normalized["narrative_threads"] and (outline or normalized["timeline"]):
        normalized["narrative_threads"] = _build_narrative_threads(
            outline or normalized["timeline"]
        )
    for thread in normalized["narrative_threads"]:
        thread.setdefault("id", _thread_id(str(thread.get("title", "未命名线程"))))
        thread.setdefault("description", str(thread.get("title", "")))
        thread.setdefault("kind", "foreshadowing")
        thread.setdefault("priority", "minor")
        thread.setdefault("status", "planned")
        thread.setdefault("introduced_chapter", 0)
        thread.setdefault("due_chapter", None)
        thread.setdefault("resolved_chapter", None)
        thread.setdefault("source", "outline")
        thread.setdefault("beats", [])
        for beat in thread["beats"]:
            beat.setdefault("status", "planned")
    return normalized


def _advance_narrative_threads(canon: dict[str, Any], chapter: dict[str, Any]) -> None:
    number = int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)
    if number <= 0:
        return
    threads = canon["narrative_threads"]
    by_id = {str(item.get("id", "")): item for item in threads}

    # 幂等重放同一终稿时，先撤销该章自动完成标记，再按当前章节重新推进。
    for thread in threads:
        for beat in thread.get("beats") or []:
            if int(beat.get("chapter", 0) or 0) == number and beat.get("managed_by") != "human":
                beat["status"] = "planned"
        if int(thread.get("resolved_chapter", 0) or 0) == number and thread.get("managed_by") != "human":
            thread["resolved_chapter"] = None

    for index, beat in enumerate(narrative_beats_from_chapter(chapter), start=1):
        thread_id = _thread_id(beat["thread"])
        thread = by_id.get(thread_id)
        if thread is None:
            thread = {
                "id": thread_id,
                "title": beat["thread"],
                "description": beat["description"],
                "kind": beat.get("kind", "foreshadowing"),
                "priority": beat.get("priority", "minor"),
                "status": "planned",
                "introduced_chapter": number,
                "due_chapter": number if beat["action"] == "resolve" else beat.get("due_chapter"),
                "resolved_chapter": None,
                "source": "chapter",
                "beats": [],
            }
            threads.append(thread)
            by_id[thread_id] = thread
        beat_id = str(beat.get("beat_id", ""))
        matching = next(
            (
                item for item in thread.get("beats") or []
                if (beat_id and str(item.get("id", "")) == beat_id)
                or (
                    not beat_id
                    and int(item.get("chapter", 0) or 0) == number
                    and item.get("action") == beat["action"]
                    and item.get("description") == beat["description"]
                )
            ),
            None,
        )
        if matching is None:
            matching = {
                "id": f"{thread_id}:beat:{number}:{beat['action']}:{index}",
                "chapter": number,
                "action": beat["action"],
                "description": beat["description"],
                "status": "planned",
            }
            thread.setdefault("beats", []).append(matching)
        matching["status"] = "completed"
        matching["completed_at"] = _now()
        if beat.get("scene_number"):
            matching["scene_number"] = beat["scene_number"]

    for thread in threads:
        completed = [
            beat for beat in (thread.get("beats") or [])
            if beat.get("status") == "completed"
        ]
        resolved = [beat for beat in completed if beat.get("action") == "resolve"]
        if resolved and thread.get("managed_by") != "human":
            resolved_chapter = max(int(beat.get("chapter", 0) or 0) for beat in resolved)
            thread["status"] = "resolved"
            thread["resolved_chapter"] = resolved_chapter
        elif completed and thread.get("status") not in {"resolved", "abandoned"}:
            thread["status"] = "open"
    threads.sort(
        key=lambda item: (int(item.get("introduced_chapter", 0) or 0), str(item.get("title", "")))
    )


def record_final_chapter(
    canon: dict[str, Any],
    chapter: dict[str, Any],
) -> dict[str, Any]:
    """幂等地将一章终稿写入时间线、角色出场记录和事实表。"""
    updated = ensure_canon(canon, world_bible="", characters=[], outline=[])
    number = int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)
    if number <= 0:
        return updated

    final_entry = _timeline_entry(chapter, status="final")
    timeline = [
        item for item in updated["timeline"]
        if int(item.get("chapter", 0) or 0) != number
    ]
    timeline.append(final_entry)
    timeline.sort(key=lambda item: int(item.get("chapter", 0) or 0))
    updated["timeline"] = timeline

    names = chapter.get("characters") or []
    if isinstance(names, str):
        names = [names]
    aliases = updated.get("aliases") or {}
    for name in names:
        key = str(name.get("name", "")).strip() if isinstance(name, dict) else str(name).strip()
        key = str(aliases.get(key, key)).strip()
        if not key:
            continue
        record = updated["characters"].setdefault(key, _character_record({"name": key}))
        appearances = [int(item) for item in record.get("appearances", []) if str(item).isdigit()]
        if number not in appearances:
            appearances.append(number)
        record["appearances"] = sorted(appearances)
        record["last_seen_chapter"] = max(int(record.get("last_seen_chapter", 0) or 0), number)

    chapter_source = f"chapter:{number}"
    fact_id = f"{chapter_source}:summary"
    facts = [item for item in updated["facts"] if item.get("source") != chapter_source]
    summary = str(chapter.get("summary", "")).strip()
    if summary:
        facts.append({
            "id": fact_id,
            "kind": "chapter_summary",
            "subject": f"第{number}章",
            "value": summary[:500],
            "source": chapter_source,
            "status": "active",
        })
    for kind, values in (("event", chapter.get("events") or []), ("location", chapter.get("locations") or [])):
        if isinstance(values, str):
            values = [values]
        for index, value in enumerate(values, start=1):
            text = str(value).strip()
            if not text:
                continue
            item_id = f"chapter:{number}:{kind}:{index}"
            facts = [item for item in facts if item.get("id") != item_id]
            facts.append({
                "id": item_id,
                "kind": kind,
                "subject": f"第{number}章",
                "value": text[:500],
                "source": chapter_source,
                "status": "active",
            })
    extracted_facts = chapter.get("extracted_facts") or []
    if isinstance(extracted_facts, dict):
        extracted_facts = [extracted_facts]
    for index, value in enumerate(extracted_facts, start=1):
        if not isinstance(value, dict):
            continue
        subject = str(value.get("subject", "")).strip()
        fact_value = str(value.get("value", "")).strip()
        if not subject or not fact_value:
            continue
        facts.append({
            "id": f"chapter:{number}:extracted:{index}",
            "kind": str(value.get("kind", "event")).strip()[:80] or "event",
            "subject": subject[:200],
            "value": fact_value[:500],
            "source": chapter_source,
            "status": "active",
        })
    updated["facts"] = facts
    _advance_narrative_threads(updated, chapter)
    return updated


def replace_final_chapter(
    canon: dict[str, Any],
    chapter: dict[str, Any],
) -> dict[str, Any]:
    """替换一章终稿，并撤销该章旧的角色出场与自动线程完成状态。"""
    updated = ensure_canon(canon, world_bible="", characters=[], outline=[])
    number = int(chapter.get("chapter_number", chapter.get("chapter", 0)) or 0)
    if number <= 0:
        return updated

    for record in updated.get("characters", {}).values():
        appearances = [
            int(item)
            for item in record.get("appearances", [])
            if str(item).isdigit() and int(item) != number
        ]
        record["appearances"] = sorted(appearances)
        record["last_seen_chapter"] = max(appearances, default=0)

    for thread in updated.get("narrative_threads") or []:
        for beat in thread.get("beats") or []:
            if int(beat.get("chapter", 0) or 0) == number:
                beat["status"] = "planned"
                beat.pop("completed_at", None)
                beat.pop("scene_number", None)
        if thread.get("managed_by") == "human":
            continue
        completed = [
            beat for beat in (thread.get("beats") or [])
            if beat.get("status") == "completed"
        ]
        resolved = [beat for beat in completed if beat.get("action") == "resolve"]
        if resolved:
            thread["status"] = "resolved"
            thread["resolved_chapter"] = max(
                int(beat.get("chapter", 0) or 0) for beat in resolved
            )
        elif completed:
            thread["status"] = "open"
            thread["resolved_chapter"] = None
        else:
            thread["status"] = "planned"
            thread["resolved_chapter"] = None

    return record_final_chapter(updated, chapter)


def apply_outline_revision(
    canon: dict[str, Any],
    outline: list[dict[str, Any]],
) -> dict[str, Any]:
    """以新大纲重建未来时间线和非人工线程，同时保留既有 Canon 治理结果。"""
    updated = ensure_canon(canon, world_bible="", characters=[], outline=[])
    existing_threads = {
        str(item.get("id", "")): item
        for item in updated.get("narrative_threads") or []
    }
    rebuilt_threads = _build_narrative_threads(outline)
    merged_threads: list[dict[str, Any]] = []
    for thread in rebuilt_threads:
        old = existing_threads.get(str(thread.get("id", "")))
        if old and old.get("managed_by") == "human":
            merged_threads.append(deepcopy(old))
            continue
        if old:
            old_beats = {
                (
                    int(beat.get("chapter", 0) or 0),
                    str(beat.get("action", "")),
                    str(beat.get("description", "")),
                ): beat
                for beat in old.get("beats") or []
            }
            for beat in thread.get("beats") or []:
                key = (
                    int(beat.get("chapter", 0) or 0),
                    str(beat.get("action", "")),
                    str(beat.get("description", "")),
                )
                previous = old_beats.get(key)
                if previous and previous.get("status") == "completed":
                    beat.update({
                        "status": "completed",
                        "completed_at": previous.get("completed_at"),
                    })
            if old.get("status") in {"resolved", "abandoned"}:
                thread["status"] = old["status"]
                thread["resolved_chapter"] = old.get("resolved_chapter")
        merged_threads.append(thread)

    known_ids = {str(item.get("id", "")) for item in merged_threads}
    merged_threads.extend(
        deepcopy(item)
        for item in existing_threads.values()
        if item.get("managed_by") == "human"
        and str(item.get("id", "")) not in known_ids
    )
    updated["narrative_threads"] = sorted(
        merged_threads,
        key=lambda item: (
            int(item.get("introduced_chapter", 0) or 0),
            str(item.get("title", "")),
        ),
    )

    final_timeline = [
        deepcopy(item)
        for item in updated.get("timeline") or []
        if item.get("status") == "final"
    ]
    planned_timeline = [
        _timeline_entry(item, status="planned")
        for item in outline
        if int(item.get("chapter", item.get("chapter_number", 0)) or 0) > 0
        and not any(
            int(final.get("chapter", 0) or 0)
            == int(item.get("chapter", item.get("chapter_number", 0)) or 0)
            for final in final_timeline
        )
    ]
    updated["timeline"] = sorted(
        [*final_timeline, *planned_timeline],
        key=lambda item: int(item.get("chapter", 0) or 0),
    )
    return updated


def _find_fact(
    canon: dict[str, Any],
    target_type: str,
    target_id: str,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    collection_name = "world_facts" if target_type == "world_fact" else "facts"
    collection = canon[collection_name]
    for index, item in enumerate(collection):
        if str(item.get("id", "")) == target_id:
            return collection, index, item
    raise ValueError(f"Canon 事实不存在:{target_id}")


def _find_thread(canon: dict[str, Any], target_id: str) -> tuple[int, dict[str, Any]]:
    for index, item in enumerate(canon["narrative_threads"]):
        if str(item.get("id", "")) == target_id:
            return index, item
    raise ValueError(f"叙事线程不存在:{target_id}")


def _append_audit(
    canon: dict[str, Any],
    *,
    action: str,
    target: str,
    before: Any,
    after: Any,
    reason: str,
) -> None:
    audit = list(canon.get("audit") or [])
    audit.append({
        "id": f"audit:{uuid4().hex}",
        "action": action,
        "target": target,
        "before": deepcopy(before),
        "after": deepcopy(after),
        "reason": reason,
        "actor": "human",
        "created_at": _now(),
    })
    canon["audit"] = audit[-_AUDIT_LIMIT:]


def apply_canon_operation(
    canon: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any]:
    """应用一次人工 Canon 治理操作并记录审计日志。"""
    updated = ensure_canon(canon, world_bible="", characters=[], outline=[])
    action = str(operation.get("action", "")).strip()
    reason = str(operation.get("reason", "")).strip()
    if not reason:
        raise ValueError("Canon 变更必须填写原因")

    if action == "upsert_fact":
        target_type = str(operation.get("target_type", "fact"))
        if target_type not in {"world_fact", "fact"}:
            raise ValueError("target_type 必须是 world_fact 或 fact")
        target_id = str(operation.get("target_id", "")).strip()
        value = str(operation.get("value", "")).strip()[:500]
        if not value:
            raise ValueError("Canon 事实内容不能为空")
        before = None
        if target_id:
            collection, index, existing = _find_fact(updated, target_type, target_id)
            before = deepcopy(existing)
            item = dict(existing)
        else:
            collection = updated["world_facts" if target_type == "world_fact" else "facts"]
            index = len(collection)
            target_id = f"manual:{uuid4().hex}"
            item = {"id": target_id, "source": "manual"}
        if target_type == "world_fact":
            path = str(operation.get("path", item.get("path", ""))).strip()
            if not path:
                raise ValueError("世界事实必须填写路径")
            item.update({"path": path, "value": value})
        else:
            subject = str(operation.get("subject", item.get("subject", ""))).strip()
            if not subject:
                raise ValueError("章节事实必须填写主体")
            item.update({
                "kind": str(operation.get("kind", item.get("kind", "manual"))).strip() or "manual",
                "subject": subject,
                "value": value,
            })
        item.update({
            "status": "active",
            "managed_by": "human",
            "updated_at": _now(),
        })
        if index < len(collection):
            collection[index] = item
        else:
            collection.append(item)
        _append_audit(
            updated,
            action=action,
            target=target_id,
            before=before,
            after=item,
            reason=reason,
        )
        return updated

    if action in {"deprecate_fact", "confirm_fact"}:
        target_type = str(operation.get("target_type", "fact"))
        if target_type not in {"world_fact", "fact"}:
            raise ValueError("target_type 必须是 world_fact 或 fact")
        target_id = str(operation.get("target_id", "")).strip()
        collection, index, existing = _find_fact(updated, target_type, target_id)
        before = deepcopy(existing)
        item = {
            **existing,
            "status": "deprecated" if action == "deprecate_fact" else "active",
            "managed_by": "human",
            "updated_at": _now(),
        }
        collection[index] = item
        _append_audit(
            updated,
            action=action,
            target=target_id,
            before=before,
            after=item,
            reason=reason,
        )
        return updated

    if action == "merge_alias":
        alias = str(operation.get("alias", "")).strip()
        canonical_name = str(operation.get("canonical_name", "")).strip()
        if not alias or not canonical_name or alias == canonical_name:
            raise ValueError("角色别名与规范名必须有效且不同")
        if canonical_name not in updated["characters"]:
            raise ValueError(f"规范角色不存在:{canonical_name}")
        before = {
            "aliases": deepcopy(updated.get("aliases") or {}),
            "alias_character": deepcopy(updated["characters"].get(alias)),
        }
        aliases = dict(updated.get("aliases") or {})
        aliases[alias] = canonical_name
        aliases = {
            key: canonical_name if value == alias else value
            for key, value in aliases.items()
        }
        updated["aliases"] = aliases
        alias_record = updated["characters"].pop(alias, None)
        if alias_record:
            canonical = updated["characters"][canonical_name]
            appearances = set(canonical.get("appearances") or []) | set(
                alias_record.get("appearances") or []
            )
            canonical["appearances"] = sorted(int(item) for item in appearances)
            canonical["last_seen_chapter"] = max(
                int(canonical.get("last_seen_chapter", 0) or 0),
                int(alias_record.get("last_seen_chapter", 0) or 0),
            )
            for field in _CHARACTER_EDITABLE_FIELDS:
                if not canonical.get(field) and alias_record.get(field):
                    canonical[field] = deepcopy(alias_record[field])
        after = {"aliases": deepcopy(updated["aliases"]), "canonical_name": canonical_name}
        _append_audit(
            updated,
            action=action,
            target=f"character:{alias}",
            before=before,
            after=after,
            reason=reason,
        )
        return updated

    if action == "update_character":
        name = str(operation.get("name", "")).strip()
        if name not in updated["characters"]:
            raise ValueError(f"角色不存在:{name}")
        patch = operation.get("patch") or {}
        if not isinstance(patch, dict):
            raise ValueError("角色修改 patch 必须是对象")
        clean_patch = {
            key: deepcopy(value)
            for key, value in patch.items()
            if key in _CHARACTER_EDITABLE_FIELDS
        }
        if not clean_patch:
            raise ValueError("角色修改没有有效字段")
        before = deepcopy(updated["characters"][name])
        updated["characters"][name].update(clean_patch)
        after = deepcopy(updated["characters"][name])
        _append_audit(
            updated,
            action=action,
            target=f"character:{name}",
            before=before,
            after=after,
            reason=reason,
        )
        return updated

    if action == "upsert_thread":
        target_id = str(operation.get("target_id", "")).strip()
        before = None
        if target_id:
            index, existing = _find_thread(updated, target_id)
            before = deepcopy(existing)
            thread = dict(existing)
        else:
            index = len(updated["narrative_threads"])
            target_id = f"thread:manual:{uuid4().hex}"
            thread = {
                "id": target_id,
                "status": "planned",
                "source": "manual",
                "beats": [],
            }
        title = str(operation.get("title", thread.get("title", ""))).strip()
        if not title:
            raise ValueError("叙事线程必须填写标题")
        priority = str(operation.get("priority", thread.get("priority", "minor"))).strip()
        if priority not in _THREAD_PRIORITIES:
            raise ValueError("priority 必须是 major 或 minor")
        introduced_chapter = _positive_int(
            operation.get("introduced_chapter", thread.get("introduced_chapter"))
        )
        if not introduced_chapter:
            raise ValueError("叙事线程必须填写有效的引入章节")
        due_raw = (
            operation.get("due_chapter")
            if "due_chapter" in operation
            else thread.get("due_chapter")
        )
        due_chapter = _positive_int(due_raw) if due_raw not in (None, "") else None
        if due_chapter and due_chapter < introduced_chapter:
            raise ValueError("叙事线程截止章节不能早于引入章节")
        thread.update({
            "title": title,
            "description": str(
                operation.get("description", thread.get("description", title))
            ).strip()[:500] or title,
            "kind": str(operation.get("kind", thread.get("kind", "foreshadowing"))).strip()[:80]
            or "foreshadowing",
            "priority": priority,
            "introduced_chapter": introduced_chapter,
            "due_chapter": due_chapter,
            "managed_by": "human",
            "updated_at": _now(),
        })
        if index < len(updated["narrative_threads"]):
            updated["narrative_threads"][index] = thread
        else:
            updated["narrative_threads"].append(thread)
        _append_audit(
            updated,
            action=action,
            target=target_id,
            before=before,
            after=thread,
            reason=reason,
        )
        return updated

    if action == "update_thread_status":
        target_id = str(operation.get("target_id", "")).strip()
        index, existing = _find_thread(updated, target_id)
        status = str(operation.get("status", "")).strip()
        if status not in _THREAD_STATUSES:
            raise ValueError("status 必须是 planned/open/resolved/abandoned")
        before = deepcopy(existing)
        thread = dict(existing)
        resolved_chapter = None
        if status == "resolved":
            resolved_chapter = _positive_int(operation.get("resolved_chapter"))
            if not resolved_chapter:
                raise ValueError("解决叙事线程必须填写解决章节")
            if resolved_chapter < int(thread.get("introduced_chapter", 0) or 0):
                raise ValueError("解决章节不能早于引入章节")
        thread.update({
            "status": status,
            "resolved_chapter": resolved_chapter,
            "managed_by": "human",
            "updated_at": _now(),
        })
        updated["narrative_threads"][index] = thread
        _append_audit(
            updated,
            action=action,
            target=target_id,
            before=before,
            after=thread,
            reason=reason,
        )
        return updated

    if action == "upsert_thread_beat":
        target_id = str(operation.get("target_id", "")).strip()
        thread_index, thread = _find_thread(updated, target_id)
        beat_id = str(operation.get("beat_id", "")).strip()
        beats = list(thread.get("beats") or [])
        before = None
        if beat_id:
            try:
                beat_index = next(
                    index for index, item in enumerate(beats)
                    if str(item.get("id", "")) == beat_id
                )
            except StopIteration as exc:
                raise ValueError(f"叙事 beat 不存在:{beat_id}") from exc
            before = deepcopy(beats[beat_index])
            beat = dict(beats[beat_index])
        else:
            beat_index = len(beats)
            beat_id = f"{target_id}:beat:manual:{uuid4().hex}"
            beat = {"id": beat_id, "status": "planned"}
        chapter = _positive_int(operation.get("chapter", beat.get("chapter")))
        if not chapter:
            raise ValueError("叙事 beat 必须填写有效章节")
        if chapter < int(thread.get("introduced_chapter", 0) or 0):
            raise ValueError("叙事 beat 章节不能早于线程引入章节")
        beat_action = _thread_action(operation.get("beat_action", beat.get("action", "")), "")
        if beat_action not in _THREAD_ACTIONS:
            raise ValueError("beat_action 必须是 setup/develop/resolve")
        description = str(operation.get("description", beat.get("description", ""))).strip()
        if not description:
            raise ValueError("叙事 beat 必须填写描述")
        beat.update({
            "chapter": chapter,
            "action": beat_action,
            "description": description[:500],
            "managed_by": "human",
            "updated_at": _now(),
        })
        scene_number = _positive_int(operation.get("scene_number"))
        if scene_number:
            beat["scene_number"] = scene_number
        elif "scene_number" in operation:
            beat.pop("scene_number", None)
        if beat_index < len(beats):
            beats[beat_index] = beat
        else:
            beats.append(beat)
        beats.sort(key=lambda item: (int(item.get("chapter", 0) or 0), str(item.get("action", ""))))
        updated_thread = {**thread, "beats": beats, "managed_by": "human", "updated_at": _now()}
        if beat_action == "resolve" and not _positive_int(updated_thread.get("due_chapter")):
            updated_thread["due_chapter"] = chapter
        updated["narrative_threads"][thread_index] = updated_thread
        _append_audit(
            updated,
            action=action,
            target=beat_id,
            before=before,
            after=beat,
            reason=reason,
        )
        return updated

    raise ValueError(f"不支持的 Canon 操作:{action}")


def format_canon(
    canon: dict[str, Any] | None,
    max_chars: int = 4000,
    current_chapter: int | None = None,
) -> str:
    """将 Canon 压缩成适合写作与质检 Prompt 的稳定文本。"""
    if not canon:
        return "暂无结构化 Canon。"
    lines = [f"Canon 版本:{canon.get('version', CANON_VERSION)}", "章节时间线:"]
    timeline = sorted(
        canon.get("timeline") or [],
        key=lambda item: int(item.get("chapter", 0) or 0),
    )
    if current_chapter is not None:
        completed = [
            item for item in timeline
            if item.get("status") == "final" and int(item.get("chapter", 0) or 0) < current_chapter
        ][-5:]
        nearby = [
            item for item in timeline
            if current_chapter - 1 <= int(item.get("chapter", 0) or 0) <= current_chapter + 2
        ]
        selected: dict[int, dict[str, Any]] = {
            int(item.get("chapter", 0) or 0): item for item in [*completed, *nearby]
        }
        timeline = [selected[key] for key in sorted(selected)]
    else:
        timeline = timeline[-12:]
    for item in timeline:
        details = [
            f"第{item.get('chapter')}章",
            str(item.get("title", "")),
            f"状态={item.get('status', '')}",
            str(item.get("summary", "")),
        ]
        if "time_days" in item:
            details.append(f"time_days={item['time_days']}")
        if item.get("emotion"):
            details.append(f"情绪={item['emotion']}")
        lines.append("- " + " | ".join(details))

    lines.append("角色状态:")
    for name, record in (canon.get("characters") or {}).items():
        lines.append(
            f"- {name} | 身份:{record.get('role', '')} | 性格:{record.get('personality', '')} "
            f"| 最近出场:{record.get('last_seen_chapter', 0)}"
        )

    aliases = canon.get("aliases") or {}
    if aliases:
        lines.append("角色别名:")
        lines.extend(f"- {alias} => {name}" for alias, name in sorted(aliases.items()))

    lines.append("叙事线程:")
    threads = canon.get("narrative_threads") or []
    for thread in threads:
        if thread.get("status") == "abandoned":
            continue
        beats = thread.get("beats") or []
        if current_chapter is not None:
            nearby_beats = [
                beat for beat in beats
                if current_chapter - 1 <= int(beat.get("chapter", 0) or 0) <= current_chapter + 1
            ]
            if thread.get("status") == "resolved" and not nearby_beats:
                continue
        else:
            nearby_beats = beats[-3:]
        due = thread.get("due_chapter") or "未定"
        line = (
            f"- [{thread.get('priority', 'minor')}/{thread.get('status', 'planned')}] "
            f"{thread.get('title', '')} | 引入={thread.get('introduced_chapter', 0)} | 截止={due}"
        )
        if nearby_beats:
            beat_text = "; ".join(
                f"第{beat.get('chapter')}章 {beat.get('action')}:{beat.get('description')}"
                for beat in nearby_beats
            )
            line += f" | 近期 beat={beat_text}"
        lines.append(line)

    lines.append("已确认事实:")
    lines.extend(
        f"- {item.get('subject')}: {item.get('value')} ({item.get('source')})"
        for item in canon.get("facts") or []
        if item.get("status", "active") == "active"
    )
    lines.append("世界事实:")
    world_facts = canon.get("world_facts") or []
    lines.extend(
        f"- {item.get('path')}: {item.get('value')}"
        for item in world_facts
        if item.get("status", "active") == "active"
    )
    return "\n".join(lines)[:max_chars]
