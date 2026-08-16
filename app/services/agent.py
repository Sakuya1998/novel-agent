"""小说创作 Agent:上下文构建 + 生成流水线。"""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from .. import prompts
from ..core.logging import get_logger
from .llm import LLMClient, LLMError, LLMOptions

logger = get_logger("novel.agent")

# ---------------- mock provider 的离线演示输出 ----------------
MOCK_PREMISE = """## 书名
《雾起长河》 《渡鸦与灯》——推荐《雾起长河》
## 类型与基调
东方悬疑,克制冷静的笔触,暗流涌动。
## 世界观与背景
架空王朝「大衍」,京城依长河而建,漕运即命脉;近年河雾中频发失踪案,坊间传言与三十年前的旧案有关。
## 核心冲突
新任河道御史沈青梧追查雾中失踪案,发现真相直指恩师与整个漕运利益集团,法理与恩义不可两全。
## 主线梗概
(此处为离线演示文本,接入真实模型后即可生成完整内容。)沈青梧入京赴任,首夜便遇雾中命案。她沿着旧档追索,逐步揭开三十年前沉船案的真相,盟友与仇敌几度易位,最终在河祭之夜与幕后之人正面对决,以放弃仕途为代价换得真相大白。
## 叙事视角与文风
第三人称有限视角,细腻写实,悬念层层推进。"""

MOCK_CHARACTERS = json.dumps(
    [
        {
            "name": "沈青梧",
            "role": "主角",
            "appearance": "青衫御史,眉眼清冷,左手常戴一枚旧银戒",
            "personality": "外冷内热,言辞精准,不信直觉只信证据",
            "background": "寒门出身,由恩师裴相扶持入仕",
            "goal": "查清父亲当年沉河的真相",
            "arc": "从唯法理是从,到理解法理之外尚有人心",
            "relationships": "裴慎之(恩师)、陆昭(搭档,渐生信任)",
        },
        {
            "name": "裴慎之",
            "role": "导师/隐秘反派",
            "appearance": "鬓发霜白,永远含笑的老相国",
            "personality": "温润如玉,滴水不漏",
            "background": "三朝元老,漕运改革的主导者",
            "goal": "守住三十年前用性命换来的秘密",
            "arc": "从庇护者滑向守护者与加害者的合一",
            "relationships": "沈青梧(学生,亦是旧案遗孤)",
        },
        {
            "name": "陆昭",
            "role": "挚友",
            "appearance": "漕帮出身的年轻捕头,笑起来有虎牙",
            "personality": "江湖气,重诺,看似散漫实则心细",
            "background": "漕帮孤儿,对河道了如指掌",
            "goal": "替枉死的帮众讨回公道",
            "arc": "从独行者变为甘愿托付后背的同伴",
            "relationships": "沈青梧(从互相提防到生死之交)",
        },
    ],
    ensure_ascii=False,
    indent=2,
)

MOCK_OUTLINE = json.dumps(
    [
        {
            "index": i,
            "title": t,
            "summary": s,
            "key_events": e,
        }
        for i, (t, s, e) in enumerate(
            [
                (
                    "雾夜命案",
                    "沈青梧入京首夜,长河雾中浮出漕船尸首,她封锁现场与府衙产生冲突。",
                    "入京;雾中命案;初见陆昭",
                ),
                (
                    "旧档疑云",
                    "沈青梧调阅三十年前沉船旧档,发现关键页缺失,恩师裴慎之亲自设宴压案。",
                    "调档;缺页;恩师设宴",
                ),
                (
                    "漕帮暗线",
                    "陆昭带沈青梧夜访漕帮,得知失踪者皆有共同特征,危险开始逼近。",
                    "夜访漕帮;线索浮现;第一次遇袭",
                ),
                ("河祭之约", "线索直指河祭之夜,沈青梧决定将计就计,与幕后之人正面相见。", "将计就计;身份揭穿;真相大白"),
            ],
            start=1,
        )
    ],
    ensure_ascii=False,
    indent=2,
)

MOCK_CHAPTER = (
    "雾是从子时漫起来的。\n\n"
    "沈青梧立在河堤上,看那团灰白沿着水面缓缓爬升,像一只有耐心的兽。身后的灯笼被水汽浸得发暗,"
    "她提着的公文袋上凝了一层细珠。进城不过半日,她已听过三遍同样的告诫:雾夜莫近长河。\n\n"
    "「大人,回吧。」随从的声音压得极低。\n\n"
    "她没有应声。雾的深处,有什么东西正顺流而下,先是桅杆,然后是半张泡胀的脸。\n\n"
    "尸体靠岸的那一刻,整座河埠的灯火,次第亮了起来。\n\n"
    "(离线演示文本:接入真实模型后,这里将按大纲生成完整章节。)"
)


def extract_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("模型未返回有效的 JSON 数组,请重试或更换模型。")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("模型返回的不是 JSON 数组,请重试。")
    return data


def normalize_characters(raw: list[Any]) -> list[dict[str, Any]]:
    keys = ["name", "role", "appearance", "personality", "background", "goal", "arc", "relationships"]
    out = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        fields = {k: str(item.get(k, "") or "").strip()[:2000] for k in keys}
        out.append(fields)
    if not out:
        raise ValueError("模型返回的角色数据无效,请重试。")
    return out


def normalize_outline(raw: list[Any]) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        summary = str(item.get("summary", "") or "").strip()
        if not title and not summary:
            continue
        try:
            index = int(item.get("index", i))
        except (TypeError, ValueError):
            index = i
        out.append(
            {
                "index": index,
                "title": title[:200] or f"第{i}章",
                "summary": summary[:2000],
                "key_events": str(item.get("key_events", "") or "")[:1000],
            }
        )
    if not out:
        raise ValueError("模型返回的大纲数据无效,请重试。")
    return out


class NovelAgent:
    """围绕一个小说项目执行的生成流水线。"""

    def __init__(self, settings: dict[str, Any], options: LLMOptions | None = None):
        self.settings = settings
        self.llm = LLMClient(
            provider=settings.get("provider", "openai"),
            model=settings.get("model", ""),
            api_key=settings.get("api_key", ""),
            base_url=settings.get("base_url", ""),
            options=options,
        )
        self.temperature = float(settings.get("temperature", 0.8))
        self.chapter_words = int(settings.get("chapter_words", 2500))

    # ---------- 基础流 ----------
    async def _stream(
        self, system: str, user: str, mock_text: str, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        async for chunk in self.llm.stream(
            system,
            user,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=max_tokens,
            mock_text=mock_text,
        ):
            yield {"type": "delta", "text": chunk}

    # ---------- 上下文构建 ----------
    @staticmethod
    def _bible(project: dict[str, Any]) -> str:
        return (project.get("premise") or "").strip() or (project.get("idea") or "").strip() or "(暂无设定)"

    @staticmethod
    def _chars_text(project: dict[str, Any]) -> str:
        chars = project.get("characters") or []
        if not chars:
            return "(暂无角色卡)"
        lines = []
        for c in chars:
            lines.append(
                f"- {c.get('name', '?')}({c.get('role', '')}):性格 {c.get('personality', '')};"
                f"目标 {c.get('goal', '')};关系 {c.get('relationships', '')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _outline_text(project: dict[str, Any]) -> str:
        outline = project.get("outline") or []
        if not outline:
            return "(暂无大纲)"
        return "\n".join(
            f"第{o.get('index', i + 1)}章《{o.get('title', '')}》:{o.get('summary', '')}" for i, o in enumerate(outline)
        )

    @staticmethod
    def _plan(project: dict[str, Any], index: int) -> dict[str, str]:
        for o in project.get("outline") or []:
            if int(o.get("index", 0)) == index:
                return {
                    "title": o.get("title", ""),
                    "summary": o.get("summary", ""),
                    "key_events": o.get("key_events", ""),
                }
        return {"title": f"第{index}章", "summary": "", "key_events": ""}

    @staticmethod
    def get_chapter(project: dict[str, Any], index: int) -> dict[str, Any] | None:
        for ch in project.get("chapters") or []:
            if int(ch.get("index", 0)) == index:
                return ch
        return None

    def _prev_context(self, project: dict[str, Any], index: int) -> str:
        """写作第 index 章时的前文上下文:优先摘要,无摘要取正文结尾。"""
        parts = []
        for ch in sorted(project.get("chapters") or [], key=lambda c: int(c.get("index", 0))):
            ci = int(ch.get("index", 0))
            if ci >= index:
                continue
            summary = (ch.get("summary") or "").strip()
            if not summary:
                content = ch.get("content") or ""
                summary = f"(暂无摘要,正文结尾:){content[-400:]}" if content else "(本章无内容)"
            parts.append(f"第{ci}章《{ch.get('title', '')}》:{summary}")
        # 只保留最近 6 章摘要,防止上下文过长
        return "\n".join(parts[-6:])

    # ---------- 生成操作(流式,yield 事件) ----------
    async def stream_premise(self, project: dict[str, Any], idea: str, genre: str) -> AsyncIterator[dict[str, Any]]:
        user = prompts.premise_prompt(
            idea or project.get("idea", ""), genre or project.get("genre", ""), self.chapter_words
        )
        async for ev in self._stream(prompts.SYSTEM_AUTHOR, user, mock_text=MOCK_PREMISE):
            yield ev

    async def stream_characters(self, project: dict[str, Any], count: int) -> AsyncIterator[dict[str, Any]]:
        premise = self._bible(project)
        user = prompts.characters_prompt(premise, count)
        async for ev in self._stream(prompts.SYSTEM_AUTHOR, user, mock_text=MOCK_CHARACTERS):
            yield ev

    async def stream_outline(self, project: dict[str, Any], num_chapters: int) -> AsyncIterator[dict[str, Any]]:
        user = prompts.outline_prompt(self._bible(project), self._chars_text(project), num_chapters)
        async for ev in self._stream(prompts.SYSTEM_AUTHOR, user, mock_text=MOCK_OUTLINE):
            yield ev

    async def stream_chapter(
        self, project: dict[str, Any], index: int, mode: str, instruction: str = ""
    ) -> AsyncIterator[dict[str, Any]]:
        plan = self._plan(project, index)
        bible, chars, outline = self._bible(project), self._chars_text(project), self._outline_text(project)
        if mode == "polish":
            ch = self.get_chapter(project, index)
            if not ch or not (ch.get("content") or "").strip():
                raise LLMError("本章还没有正文,无法润色。")
            user = prompts.chapter_polish_prompt(bible, chars, index, ch["content"], instruction)
        else:
            existing_tail = ""
            if mode == "continue":
                ch = self.get_chapter(project, index)
                content = (ch or {}).get("content") or ""
                if not content.strip():
                    raise LLMError("本章还没有正文,请先使用「AI 写作」。")
                existing_tail = content[-1200:]
            user = prompts.chapter_write_prompt(
                bible,
                chars,
                outline,
                self._prev_context(project, index),
                index,
                plan["title"],
                plan["summary"],
                plan["key_events"],
                self.chapter_words,
                existing_tail=existing_tail,
                instruction=instruction,
            )
        async for ev in self._stream(prompts.SYSTEM_AUTHOR, user, mock_text=MOCK_CHAPTER):
            yield ev

    async def summarize_text(self, text: str) -> str:
        buf = ""
        async for chunk in self.llm.stream(
            prompts.SYSTEM_AUTHOR,
            prompts.summary_prompt(text),
            temperature=0.3,
            max_tokens=512,
            mock_text="沈青梧入京首夜遇雾中命案,封锁现场与府衙冲突;调阅旧档发现关键缺页,恩师设宴压案,暗中另有势力注视着她。",
        ):
            buf += chunk
        return buf.strip()[:600]
