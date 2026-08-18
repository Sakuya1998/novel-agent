"""命令行入口:创建小说或恢复持久化的人工审查现场。"""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from config import STYLE_PROFILES, Config
from graph.builder import build_graph
from graph.state import create_initial_state
from memory.sql_store import NovelStore
from models.model_settings import ModelSettingsStore
from models.resolver import ModelResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")

_NOISE_NODES = {"LangGraph", "branch", "should_continue", "graph"}


def _chapter_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 50:
        raise argparse.ArgumentTypeError("章节数必须在 1 到 50 之间")
    return count


async def run_novel_pipeline(
    args: argparse.Namespace,
    *,
    config: Config | None = None,
    store: NovelStore | None = None,
) -> None:
    """创建新作品或从 SQLite 检查点恢复创作图。"""
    cfg = config or Config()
    cfg.ensure_dirs()
    novel_store = store or NovelStore(cfg)
    model_resolver = ModelResolver(config=cfg, store=ModelSettingsStore(cfg))

    if args.resume:
        novel_id = str(args.resume)
        novel = novel_store.get_novel(novel_id)
        if not novel:
            raise RuntimeError(f"小说不存在:{novel_id}")
    else:
        model_resolver.validate_runtime()
        novel_id = f"novel_{uuid4().hex[:8]}"
        novel = novel_store.create_novel(
            novel_id=novel_id,
            title=args.title,
            genre=args.genre,
            style=args.style,
            total_chapters=args.chapters,
            inspiration=args.inspiration,
            creative_brief=None,
        )

    graph_config = {"configurable": {"thread_id": novel_id}}
    async with AsyncSqliteSaver.from_conn_string(cfg.checkpoint_db_path) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        snapshot = await graph.aget_state(graph_config)

        if args.resume:
            if not snapshot.values:
                chapters = novel_store.get_all_chapters(novel_id)
                if len(chapters) >= int(novel["total_chapters"] or 0):
                    print(f"小说 {novel_id} 已完成,无需恢复。")
                    return
                raise RuntimeError("旧作品缺少 LangGraph 检查点,仅支持查看和导出")
            if not snapshot.next:
                print(f"小说 {novel_id} 已运行至 END。")
                return
            if "human_review" in snapshot.next:
                if args.auto:
                    state_values: object = Command(resume="approve")
                elif args.feedback is not None:
                    if args.version_number is not None:
                        chapter_number = int(
                            snapshot.values.get("current_draft", {}).get(
                                "chapter_number",
                                snapshot.values.get("current_chapter", 0),
                            )
                        )
                        if novel_store.get_chapter_version(
                            novel_id,
                            chapter_number,
                            args.version_number,
                        ) is None:
                            raise RuntimeError(f"章节版本 v{args.version_number} 不存在")
                        state_values = Command(resume={
                            "action": "restore_version",
                            "version_number": args.version_number,
                        })
                    elif args.scene_number is not None:
                        scene_numbers = {
                            int(item.get("scene_number", 0))
                            for item in (
                                snapshot.values.get("current_draft", {}).get("scene_plan")
                                or snapshot.values.get("scene_plan")
                                or []
                            )
                        }
                        if args.scene_number not in scene_numbers:
                            raise RuntimeError(f"场景 {args.scene_number} 不存在")
                        state_values = Command(resume={
                            "feedback": args.feedback,
                            "scene_number": args.scene_number,
                        })
                    else:
                        state_values = Command(resume=args.feedback)
                else:
                    print(f"小说 {novel_id} 正在等待人工审查。")
                    print(f"恢复命令: python main.py --resume {novel_id} --feedback approve")
                    return
            else:
                state_values = None
        else:
            state_values = create_initial_state(
                novel_id=novel_id,
                title=str(args.title),
                genre=str(args.genre),
                inspiration=str(args.inspiration),
                total_chapters=int(args.chapters),
                style=str(args.style),
                creative_brief=novel.get("creative_brief"),
                creative_brief_version=int(novel.get("creative_brief_version", 1) or 1),
                config=cfg,
            )

        if args.resume:
            model_resolver.validate_runtime()

        print(
            f"\n{'=' * 60}\n  创作:《{novel['title']}》 "
            f"{novel['total_chapters']} 章 · {novel['style']}\n{'=' * 60}\n"
        )

        while True:
            async for event in graph.astream_events(state_values, graph_config, version="v2"):
                if event["event"] == "on_chain_end" and event["name"] not in _NOISE_NODES:
                    print(f"[节点完成] {event['name']}")

            snapshot = await graph.aget_state(graph_config)
            if not snapshot.next:
                break
            if "human_review" in snapshot.next:
                if args.auto:
                    print("[人工审查] auto 模式自动通过")
                    state_values = Command(resume="approve")
                    continue
                if snapshot.values.get("persistence_error"):
                    print(f"[定稿重试] {snapshot.values['persistence_error']}")
                print(f"\n[人工审查] 已持久化暂停现场,novel_id: {novel_id}")
                print(f"恢复命令: python main.py --resume {novel_id} --feedback approve")
                break
            state_values = None

        final = (await graph.aget_state(graph_config)).values

    chapters = final.get("chapters") or []
    finished = int(final.get("current_chapter", 1)) > int(novel["total_chapters"] or 0)
    status = "创作完成" if finished else "创作已暂停"
    print(f"\n{'=' * 60}\n  {status}:{len(chapters)} 章,共 {sum(c.get('word_count', 0) for c in chapters)} 字")
    print(f"  novel_id: {novel_id}")
    print(f"{'=' * 60}\n")

    for chapter in chapters:
        print(
            f"  第{chapter.get('chapter_number')}章 {chapter.get('title')}"
            f"({chapter.get('word_count', 0)}字)"
        )
        print(f"    {(chapter.get('summary') or '')[:80]}...")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-Agent 小说创作系统")
    parser.add_argument("--title", help="小说标题")
    parser.add_argument("--genre", default="武侠", help="类型:武侠/科幻/言情 等")
    parser.add_argument("--inspiration", help="一句话灵感")
    parser.add_argument("--chapters", type=_chapter_count, default=3, help="总章节数(1-50)")
    parser.add_argument("--style", default="jin_yong", choices=sorted(STYLE_PROFILES), help="风格")
    parser.add_argument("--auto", action="store_true", help="人工审查自动通过")
    parser.add_argument("--resume", metavar="NOVEL_ID", help="恢复已有作品的持久化检查点")
    parser.add_argument("--feedback", help="恢复人工审查时提交 approve 或修改意见")
    parser.add_argument(
        "--scene-number",
        type=int,
        choices=range(1, 9),
        help="将 --feedback 仅应用于指定场景(1-8)",
    )
    parser.add_argument(
        "--version-number",
        type=int,
        help="恢复人工审查时回滚到指定章节版本",
    )
    args = parser.parse_args(argv)

    if args.resume:
        if args.title or args.inspiration:
            parser.error("--resume 不能与 --title/--inspiration 同时使用")
        if args.scene_number is not None and args.version_number is not None:
            parser.error("--scene-number 与 --version-number 不能同时使用")
        if args.scene_number is not None:
            if not args.feedback:
                parser.error("--scene-number 必须同时提供 --feedback")
            if args.feedback.strip().lower() in {"approve", "通过", "y", "yes"}:
                parser.error("--scene-number 不能与通过指令一起使用")
        if args.version_number is not None and args.feedback is None:
            args.feedback = "restore"
    else:
        if not args.title or not args.inspiration:
            parser.error("新建作品必须提供 --title 和 --inspiration")
        if args.feedback is not None:
            parser.error("--feedback 只能与 --resume 一起使用")
        if args.scene_number is not None:
            parser.error("--scene-number 只能与 --resume 一起使用")
        if args.version_number is not None:
            parser.error("--version-number 只能与 --resume 一起使用")
    return args


def main() -> None:
    try:
        asyncio.run(run_novel_pipeline(parse_args()))
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
