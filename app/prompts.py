"""提示词模板 — 面向中文长篇小说创作。"""

SYSTEM_AUTHOR = (
    "你是一位笔力深厚的职业小说作家,擅长细腻的场景描写、鲜活的人物对白和紧凑的情节节奏。"
    "严格依据给定的设定与上下文创作,保持人物、情节、时间线完全一致。"
    "只输出被要求的内容,不要输出任何解释、开场白、注释或代码块标记。"
)


def premise_prompt(idea: str, genre: str, chapter_words: int) -> str:
    return f"""请为一部长篇小说撰写完整的「故事圣经」(设定总纲)。

【创作意向】{idea or "(请自由发挥)"}
【类型】{genre or "不限"}
【单章篇幅】约 {chapter_words} 字

按以下结构输出(用 Markdown 二级标题分节,内容要具体、可直接指导写作):
## 书名
给出 2~3 个备选书名,并注明推荐哪一个
## 类型与基调
## 世界观与背景
时代、地点、独特规则体系(如力量体系/社会结构),要具体可感
## 核心冲突
主要矛盾、对手与层层递进的对抗形式
## 主线梗概
400~600 字,涵盖开端、发展、转折、高潮与结局走向
## 叙事视角与文风
建议人称、语言风格与叙事节奏
"""


def characters_prompt(premise: str, count: int) -> str:
    return f"""以下是这部小说的故事设定:

{premise}

请为主要角色建立角色卡,共 {count} 个(覆盖主角、重要配角与核心反派;若有明显的感情线、师徒线也须覆盖)。
只输出一个 JSON 数组,不要任何解释或代码块。每个元素的格式:
[
  {{
    "name": "姓名",
    "role": "定位,如:主角/女主/反派/导师/挚友",
    "appearance": "外貌与标志性特征",
    "personality": "性格、说话风格与口头禅",
    "background": "背景经历",
    "goal": "核心目标与深层动机",
    "arc": "贯穿全书的成长弧线",
    "relationships": "与其他角色的关键关系"
  }}
]
"""


def outline_prompt(premise: str, characters_text: str, num_chapters: int) -> str:
    return f"""故事设定:
{premise}

主要角色:
{characters_text}

请为全书制定分章大纲,共 {num_chapters} 章。要求:
- 前 3 章内抛出核心冲突,让主角陷入不可回头的境地;
- 中段矛盾层层升级,每 3~5 章完成一次小高潮;
- 至少埋设 3 处伏笔并在后段回收;
- 最后一章收束主线,给出有力的结局。

只输出一个 JSON 数组,不要任何解释或代码块:
[
  {{
    "index": 1,
    "title": "章节标题(简洁、有画面感)",
    "summary": "本章情节概要,100~150 字",
    "key_events": "关键事件,用分号分隔"
  }}
]
"""


def chapter_write_prompt(
    bible: str,
    characters_text: str,
    outline_text: str,
    prev_context: str,
    chapter_no: int,
    title: str,
    summary: str,
    key_events: str,
    words: int,
    existing_tail: str = "",
    instruction: str = "",
) -> str:
    plan = f"""第 {chapter_no} 章章题:{title}
本章情节计划:{summary}
本章关键事件:{key_events or "(无)"}"""
    extra = ""
    if existing_tail:
        extra = f"""
【已有正文(结尾部分)】
{existing_tail}

本次任务是在已有正文之后「无缝续写」:不要重复已有内容,不要重新开场,直接接续叙事。"""
    ins = f"\n【本次特别要求】{instruction}\n" if instruction else ""
    return f"""【故事圣经】
{bible}

【主要角色】
{characters_text}

【全书大纲】
{outline_text}

【前文梗概】
{prev_context or "(本章为开篇,暂无前文)"}

【本章任务】
{plan}

【写作要求】
1. 撰写第 {chapter_no} 章正文,目标 {words} 字左右;
2. 场景化叙事:有具体的时间、地点、感官细节与有张力的对白,拒绝流水账;
3. 人物言行必须与角色卡及前文严格一致;
4. 完整覆盖本章关键事件,事件之间自然过渡;
5. 章末留下钩子或情绪落点;
6. 只输出正文本身,不要章节号、标题、分割线或任何说明。{extra}{ins}"""


def chapter_polish_prompt(
    bible: str,
    characters_text: str,
    chapter_no: int,
    text: str,
    instruction: str = "",
) -> str:
    ins = f"\n【本次特别要求】{instruction}\n" if instruction else ""
    return f"""【故事圣经】
{bible}

【主要角色】
{characters_text}

【待润色正文】(第 {chapter_no} 章)
{text}

【润色要求】
1. 保留全部情节、人物关系与大致篇幅;
2. 提升文字质感与画面感,优化对白,收紧节奏,删减冗余;
3. 只输出润色后的完整正文,不要任何解释。{ins}"""


def summary_prompt(text: str) -> str:
    return f"""请将下面这一章正文压缩为不超过 200 字的情节摘要,涵盖:关键事件、人物关系或状态的变化、新信息与伏笔。只输出摘要本身。

【正文】
{text}"""
