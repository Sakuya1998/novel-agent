"""运行固定评测套件，并以进程退出码执行质量回归门禁。"""

import argparse
import asyncio
import json

from config import Config
from memory.sql_store import NovelStore
from tools.evaluation_benchmark import run_evaluation_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 Novel Agent 固定质量评测套件")
    parser.add_argument("--baseline-run-id", default="", help="与已保存的评测运行比较")
    parser.add_argument("--gate-threshold", type=float, default=70.0, help="绝对质量门分数")
    parser.add_argument("--regression-threshold", type=float, default=3.0, help="允许的最大回归分差")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    return parser


async def main() -> int:
    args = build_parser().parse_args()
    store = NovelStore(Config())
    baseline = store.get_evaluation_benchmark(args.baseline_run_id) if args.baseline_run_id else None
    if args.baseline_run_id and baseline is None:
        raise SystemExit(f"评测基准不存在: {args.baseline_run_id}")
    result = await run_evaluation_benchmark(
        baseline=baseline,
        gate_threshold=args.gate_threshold,
        regression_threshold=args.regression_threshold,
    )
    saved = store.save_evaluation_benchmark(result)
    if args.json:
        print(json.dumps(saved, ensure_ascii=False, indent=2))
    else:
        print(
            f"{saved['status'].upper()} {saved['overall_score']:.1f}/100 "
            f"({sum(item['passed'] for item in saved['cases'])}/{len(saved['cases'])} cases) "
            f"run={saved['id']}"
        )
    return 0 if saved["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
