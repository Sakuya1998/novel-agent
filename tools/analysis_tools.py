"""分析工具:时间线校验、角色行为验证、节奏分析(文档 6.1)。

确定性纯函数实现,不依赖 LLM —— 把可计算的检查交给代码,
LLM 只处理需要语义理解的部分。
"""

from langchain_core.tools import tool


@tool
def calculate_timeline(chapters: list[dict]) -> str:
    """检查章节时间线一致性,输出每章时间标记与检测到的冲突。

    Args:
        chapters: 章节列表,每章需含 chapter/summary,可含 time_days(距开篇天数)

    Returns:
        时间线清单与冲突报告
    """
    timeline: list[tuple[int, int | None]] = []
    for ch in sorted(chapters, key=lambda c: c.get("chapter", 0)):
        timeline.append((ch.get("chapter", 0), ch.get("time_days")))

    conflicts = []
    prev_num, prev_days = -1, None
    for num, days in timeline:
        if days is None:
            continue
        if prev_days is not None and days < prev_days:
            conflicts.append(
                f"第{num}章(time_days={days})早于第{prev_num}章(time_days={prev_days}),时间线倒流"
            )
        prev_num, prev_days = num, days

    lines = [f"时间线:{[(n, d) for n, d in timeline]}"]
    lines.append("时间线冲突:" + ("; ".join(conflicts) if conflicts else "无"))
    return "\n".join(lines)


@tool
def check_character_behavior(
    character_name: str,
    action: str,
    character_setting: str,
) -> str:
    """验证角色行为是否符合其人设设定。

    Args:
        character_name: 角色名
        action: 待验证的行为描述(一句话)
        character_setting: 角色设定文本(性格/行为模式/口头禅)

    Returns:
        一致/存疑 的启发式判定与依据(最终语义裁决交给 ConsistencyChecker)
    """
    setting_lows = character_setting.lower()
    # 启发式:行为关键词未在设定中出现即标记存疑,交 LLM 复核
    action_words = [w for w in action.replace(",", " ").split() if w]
    misses = [w for w in action_words if w.lower() not in setting_lows]
    if not misses:
        return f"「{character_name}」行为与设定关键词一致(启发式通过,建议 LLM 复核语义)。"
    return (
        f"「{character_name}」行为中的词 {misses} 未在设定中出现,"
        f"存在人设偏离风险,需一致性检查 Agent 复核。"
    )


@tool
def analyze_pacing(chapters: list[dict]) -> str:
    """分析小说节奏分布,统计各情绪基调占比与连续同调警示。

    Args:
        chapters: 章节列表,每章需含 emotion(情绪基调)

    Returns:
        节奏分布报告
    """
    emotions = [str(c.get("emotion", "未知")).strip() for c in chapters]
    if not emotions:
        return "暂无章节可分析。"

    counts: dict[str, int] = {}
    for e in emotions:
        counts[e] = counts.get(e, 0) + 1

    total = len(emotions)
    dist = ", ".join(f"{k} {v}章({v * 100 // total}%)" for k, v in counts.items())

    warnings = []
    streak = 1
    for i in range(1, len(emotions)):
        if emotions[i] == emotions[i - 1]:
            streak += 1
            if streak == 3:
                warnings.append(f"「{emotions[i]}」连续 {streak} 章及以上,节奏趋于单调")
        else:
            streak = 1

    report = [f"节奏分布(共{total}章):{dist}"]
    report.append("节奏警示:" + ("; ".join(warnings) if warnings else "无"))
    return "\n".join(report)
