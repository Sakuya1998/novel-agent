"""章节质量评测的确定性指标与回归比较。"""

import re
from collections import Counter
from typing import Any

DETERMINISTIC_SCHEMA_VERSION = "chapter-quality-v1"
JUDGE_RUBRIC_VERSION = "literary-judge-v1"


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _normalized_paragraphs(content: str) -> list[str]:
    paragraphs = [
        re.sub(r"\s+", "", item).casefold()
        for item in re.split(r"\n\s*\n|\n", content)
    ]
    return [item for item in paragraphs if item]


def _length_score(content: str, scene_plan: list[dict[str, Any]]) -> tuple[float, str]:
    target = sum(max(int(item.get("estimated_words", 0) or 0), 0) for item in scene_plan)
    actual = len(content.strip())
    if not target:
        return (100.0 if actual else 0.0), f"正文 {actual} 字，场景计划未提供字数目标"
    ratio = actual / target
    score = _clamp(100 - abs(ratio - 1) * 100)
    return score, f"正文 {actual} 字，计划 {target} 字，达成率 {ratio:.0%}"


def _scene_score(
    content: str,
    scene_plan: list[dict[str, Any]],
    scene_drafts: list[dict[str, Any]],
) -> tuple[float, str]:
    planned = [int(item.get("scene_number", 0) or 0) for item in scene_plan]
    if not planned:
        return (100.0 if content.strip() else 0.0), "未设置场景计划"
    completed = [
        int(item.get("scene_number", 0) or 0)
        for item in scene_drafts
        if str(item.get("content", "")).strip()
    ]
    planned_counter = Counter(planned)
    completed_counter = Counter(completed)
    covered = sum(1 for number in set(planned) if completed_counter[number] > 0)
    duplicates = sum(max(count - 1, 0) for count in completed_counter.values())
    extras = sum(count for number, count in completed_counter.items() if number not in planned_counter)
    score = _clamp((covered / max(len(set(planned)), 1)) * 100 - (duplicates + extras) * 12.5)
    return score, f"已执行 {covered}/{len(set(planned))} 个计划场景，重复 {duplicates}，额外 {extras}"


def _narrative_score(scene_plan: list[dict[str, Any]]) -> tuple[float, str]:
    beats = [
        beat
        for scene in scene_plan
        for beat in (scene.get("narrative_beats") or [])
        if isinstance(beat, dict)
    ]
    if not beats:
        return 100.0, "本章没有计划叙事 beat"
    keys = [
        (
            " ".join(str(beat.get("thread", beat.get("title", ""))).casefold().split()),
            str(beat.get("action", "")).casefold(),
        )
        for beat in beats
    ]
    invalid = sum(not title or action not in {"setup", "develop", "resolve"} for title, action in keys)
    duplicates = sum(max(count - 1, 0) for count in Counter(keys).values())
    score = _clamp(100 - invalid * 25 - duplicates * 20)
    return score, f"共 {len(beats)} 个 beat，无效 {invalid}，重复分配 {duplicates}"


def _structure_score(content: str, summary: str) -> tuple[float, str]:
    paragraphs = _normalized_paragraphs(content)
    score = 0.0
    if content.strip():
        score += 50
    if summary.strip():
        score += 20
    if len(paragraphs) >= 3:
        score += 20
    elif paragraphs:
        score += 10
    if len(content.strip()) >= 200:
        score += 10
    return _clamp(score), f"正文段落 {len(paragraphs)}，摘要{'完整' if summary.strip() else '缺失'}"


def _repetition_score(content: str) -> tuple[float, str]:
    paragraphs = _normalized_paragraphs(content)
    if not paragraphs:
        return 0.0, "正文为空"
    duplicate_paragraphs = sum(max(count - 1, 0) for count in Counter(paragraphs).values())
    compact = re.sub(r"\s+", "", content).casefold()
    windows = [compact[index : index + 12] for index in range(max(len(compact) - 11, 0))]
    repeated_windows = sum(max(count - 1, 0) for count in Counter(windows).values())
    repeat_ratio = repeated_windows / max(len(windows), 1)
    score = _clamp(100 - duplicate_paragraphs * 25 - min(repeat_ratio * 160, 50))
    return score, f"重复段落 {duplicate_paragraphs}，重复片段率 {repeat_ratio:.1%}"


def _consistency_score(issues: list[dict[str, Any]]) -> tuple[float, str]:
    penalties = {"high": 25, "medium": 12, "low": 5}
    counts = Counter(str(item.get("severity", "low")).lower() for item in issues)
    score = _clamp(100 - sum(penalties.get(level, 5) * count for level, count in counts.items()))
    return score, f"高/中/低问题 {counts['high']}/{counts['medium']}/{counts['low']}"


def evaluate_chapter_deterministic(
    chapter: dict[str, Any],
    *,
    issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """对任意章节快照生成完全可重算的 0-100 分指标。"""
    content = str(chapter.get("content", ""))
    scene_plan = chapter.get("scene_plan") or []
    scene_drafts = chapter.get("scene_drafts") or []
    dimensions = {
        "length_adherence": _length_score(content, scene_plan),
        "structure": _structure_score(content, str(chapter.get("summary", ""))),
        "scene_coverage": _scene_score(content, scene_plan, scene_drafts),
        "narrative_coverage": _narrative_score(scene_plan),
        "repetition_control": _repetition_score(content),
        "consistency": _consistency_score(issues or []),
    }
    scores = {name: score for name, (score, _) in dimensions.items()}
    findings = [
        {"dimension": name, "score": score, "message": message, "source": "deterministic"}
        for name, (score, message) in dimensions.items()
    ]
    return {
        "schema_version": DETERMINISTIC_SCHEMA_VERSION,
        "scores": scores,
        "overall_score": round(sum(scores.values()) / len(scores), 1),
        "findings": findings,
    }


def quality_gate_result(
    report: dict[str, Any],
    *,
    threshold: float = 70.0,
) -> dict[str, Any]:
    """把确定性评分转换为可驱动回写的质量门结论。"""
    normalized_threshold = _clamp(float(threshold))
    scores = {
        str(name): float(score)
        for name, score in (report.get("scores") or {}).items()
    }
    critical_dimensions = {"structure", "scene_coverage", "narrative_coverage", "consistency"}
    critical_failures = [
        name for name in critical_dimensions
        if float(scores.get(name, 100.0)) < 40.0
    ]
    failed = float(report.get("overall_score", 0.0)) < normalized_threshold or bool(
        critical_failures
    )
    findings = sorted(
        (
            item for item in report.get("findings") or []
            if float(item.get("score", 100.0)) < normalized_threshold
        ),
        key=lambda item: float(item.get("score", 100.0)),
    )
    notes = [
        f"- {item.get('dimension')}: {item.get('score')} 分；{item.get('message', '')}"
        for item in findings[:3]
    ]
    revision_notes = ""
    if failed:
        revision_notes = (
            f"自动质量门未通过（综合 {report.get('overall_score', 0)} / "
            f"阈值 {normalized_threshold}），请只针对以下薄弱项重写：\n"
            + ("\n".join(notes) or "- 补全章节结构、场景执行和叙事兑现")
        )
    return {
        **report,
        "threshold": normalized_threshold,
        "passed": not failed,
        "critical_failures": sorted(critical_failures),
        "revision_notes": revision_notes,
    }


def combine_quality_scores(
    deterministic_scores: dict[str, float],
    judge_scores: dict[str, float] | None = None,
) -> float:
    deterministic = sum(deterministic_scores.values()) / max(len(deterministic_scores), 1)
    if not judge_scores:
        return round(deterministic, 1)
    judge = sum(judge_scores.values()) / max(len(judge_scores), 1)
    return round(deterministic * 0.5 + judge * 0.5, 1)


def compare_evaluations(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    regression_threshold: float = 3.0,
) -> dict[str, Any]:
    """比较两次评测并给出每维变化与总体回归结论。"""
    before = {**baseline.get("deterministic_scores", {}), **baseline.get("judge_scores", {})}
    after = {**candidate.get("deterministic_scores", {}), **candidate.get("judge_scores", {})}
    dimensions = {}
    for name in sorted(set(before) | set(after)):
        if name not in before or name not in after:
            continue
        delta = round(float(after[name]) - float(before[name]), 1)
        dimensions[name] = {"from": before[name], "to": after[name], "delta": delta}
    overall_delta = round(
        float(candidate.get("overall_score", 0)) - float(baseline.get("overall_score", 0)),
        1,
    )
    if overall_delta <= -abs(regression_threshold):
        status = "regressed"
    elif overall_delta >= abs(regression_threshold):
        status = "improved"
    else:
        status = "stable"
    return {
        "from_evaluation_id": baseline.get("id"),
        "to_evaluation_id": candidate.get("id"),
        "from_version": baseline.get("version_number"),
        "to_version": candidate.get("version_number"),
        "overall_delta": overall_delta,
        "status": status,
        "regression_threshold": abs(regression_threshold),
        "dimensions": dimensions,
    }
