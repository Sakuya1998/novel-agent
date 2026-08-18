"""评测或重建指定作品的长期记忆索引。"""

import argparse
import json

from config import Config
from memory.canon import ensure_canon
from memory.hierarchical import build_hierarchical_memory
from memory.sql_store import NovelStore
from memory.vector_store import NovelMemory
from tools.memory_quality import (
    build_memory_eval_cases,
    build_memory_records,
    evaluate_memory_retrieval,
    rebuild_memory_index,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="评测或重建 Novel Agent 长期记忆索引")
    parser.add_argument("--novel-id", required=True, help="作品 ID")
    parser.add_argument("--rebuild", action="store_true", help="先清空并重建向量索引")
    parser.add_argument("--k", type=int, default=5, help="每个查询评测的召回条数")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cfg = Config()
    store = NovelStore(cfg)
    novel = store.get_novel(args.novel_id)
    if novel is None:
        raise SystemExit(f"小说不存在: {args.novel_id}")
    progress = store.get_progress(args.novel_id) or {}
    state = progress.get("state") or {}
    chapters = store.get_all_chapters(args.novel_id)
    world_bible = str(state.get("world_bible", ""))
    characters = state.get("characters") or []
    outline = state.get("outline") or []
    canon = ensure_canon(
        state.get("canon"),
        world_bible=world_bible,
        characters=characters,
        outline=outline,
        chapters=chapters,
    )
    memory_index = build_hierarchical_memory(
        chapters,
        total_chapters=int(novel.get("total_chapters", len(chapters)) or len(chapters)),
    )
    memory = NovelMemory(args.novel_id, cfg)
    rebuild = None
    if args.rebuild:
        records = build_memory_records(
            novel_id=args.novel_id,
            world_bible=world_bible,
            characters=characters,
            outline=outline,
            chapters=chapters,
            canon=canon,
            memory_index=memory_index,
        )
        rebuild = rebuild_memory_index(memory, records)
    cases = build_memory_eval_cases(
        novel_id=args.novel_id,
        world_bible=world_bible,
        characters=characters,
        outline=outline,
        chapters=chapters,
        canon=canon,
    )
    quality = evaluate_memory_retrieval(memory=memory, cases=cases, k=args.k)
    report = {"novel_id": args.novel_id, "rebuild": rebuild, "quality": quality}
    store.save_memory_quality_run(
        args.novel_id,
        mode="rebuild" if args.rebuild else "evaluate",
        index_hash=str((rebuild or quality).get("index_hash", "")),
        report=report,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"{quality['status'].upper()} {quality['passed_cases']}/{quality['case_count']} cases "
            f"Recall@{quality['k']}={quality['recall_at_k']:.2f} "
            f"MRR={quality['mrr']:.2f}"
        )
    return 0 if quality["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
