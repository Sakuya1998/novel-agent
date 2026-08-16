"""命令行入口(文档 7.2)。

用法:
    python main.py --title "剑来" --genre 武侠 --inspiration "..." --chapters 3 --style gu_long
    python main.py ... --auto   # 人工审查自动通过(全自动演示)

事件消费:astream_events(v2) 输出节点级进度;
运行到 human_review 暂停(interrupt)时,--auto 模式自动 resume approve。
"""

import argparse
import asyncio
import logging
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from config import STYLE_PROFILES, Config
from graph.builder import build_graph
from memory.sql_store import NovelStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")

# astream_events 中无需展示的内部链名
_NOISE_NODES = {"LangGraph", "branch", "should_continue", "graph"}


async def run_novel_pipeline(args: argparse.Namespace) -> None:
    """端到端运行小说创作流水线。"""
    novel_id = f"novel_{uuid4().hex[:8]}"
    cfg = Config()
    cfg.ensure_dirs()

    store = NovelStore(cfg)
    store.create_novel(
        novel_id=novel_id,
        title=args.title,
        genre=args.genre,
        style=args.style,
        total_chapters=args.chapters,
        inspiration=args.inspiration,
    )

    memory = MemorySaver()
    graph = build_graph(checkpointer=memory)
    config = {"configurable": {"thread_id": novel_id}}

    initial_state = {
        "title": args.title,
        "genre": args.genre,
        "inspiration": args.inspiration,
        "total_chapters": args.chapters,
        "style": args.style,
        "novel_id": novel_id,
        "current_chapter": 1,
        "current_phase": "writing",
        "max_revision_attempts": 2,
        "chapters": [],
    }

    print(f"\n{'=' * 60}\n  开始创作:《{args.title}》 {args.chapters} 章 · {args.style}\n{'=' * 60}\n")

    state_values: object = initial_state
    while True:
        async for event in graph.astream_events(state_values, config, version="v2"):
            if event["event"] == "on_chain_end" and event["name"] not in _NOISE_NODES:
                print(f"[节点完成] {event['name']}")

        snapshot = await graph.aget_state(config)
        if not snapshot.next:  # 运行至 END
            break
        if "human_review" in snapshot.next:
            if not args.auto:
                print("\n[人工审查] 图已暂停,交互式审查请使用 Streamlit UI 或 API。")
                break
            print("[人工审查] auto 模式自动通过")
            state_values = Command(resume="approve")
            continue
        break  # 未知暂停态,退出

    final = (await graph.aget_state(config)).values
    chapters = final.get("chapters") or []
    print(f"\n{'=' * 60}\n  创作完成:{len(chapters)} 章,共 {sum(c.get('word_count', 0) for c in chapters)} 字")
    print(f"  novel_id: {novel_id}(SQLite 已持久化,导出: python -c \"from tools import export_to_format as e\" ...)")
    print(f"{'=' * 60}\n")

    for ch in chapters:
        print(f"  第{ch.get('chapter_number')}章 {ch.get('title')}({ch.get('word_count', 0)}字)")
        print(f"    {(ch.get('summary') or '')[:80]}...")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-Agent 小说创作系统")
    parser.add_argument("--title", required=True, help="小说标题")
    parser.add_argument("--genre", default="武侠", help="类型:武侠/科幻/言情 等")
    parser.add_argument("--inspiration", required=True, help="一句话灵感")
    parser.add_argument("--chapters", type=int, default=3, help="总章节数")
    parser.add_argument("--style", default="jin_yong", choices=sorted(STYLE_PROFILES), help="风格")
    parser.add_argument("--auto", action="store_true", help="人工审查自动通过")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_novel_pipeline(parse_args()))
