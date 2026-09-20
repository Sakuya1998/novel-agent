"""Bounded opt-in compatibility smoke test against real model providers."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


def emit_report(report: dict[str, Any], report_path: Path | None) -> None:
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def credentials_available() -> bool:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return False
    return provider != "anthropic" or bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def configure_runtime(root: Path, *, token_budget: int, timeout_seconds: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "APP_ENVIRONMENT": "test",
            "AUTH_ENABLED": "false",
            "SQLITE_DB_PATH": str(root / "novels.db"),
            "CHECKPOINT_DB_PATH": str(root / "checkpoints.db"),
            "CHROMA_PERSIST_DIR": str(root / "chroma"),
            "MODEL_SECRET_KEY_PATH": str(root / "model-settings.key"),
            "TRANSFER_DIR": str(root / "transfers"),
            "RUNTIME_BACKUP_DIR": str(root / "runtime-backups"),
            "MAX_NOVEL_TOKENS": str(token_budget),
            "MAX_TOKENS": "1024",
            "MAX_CHAPTER_WORDS": "800",
            "MODEL_RETRY_ATTEMPTS": "1",
            "MODEL_TIMEOUT_SECONDS": str(min(timeout_seconds, 90)),
        }
    )


def failure_category(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in name:
        return "timeout"
    if "budget" in name:
        return "budget"
    if "configuration" in name:
        return "configuration"
    if "connection" in name:
        return "provider_connection"
    return "workflow"


async def run_smoke(root: Path, *, token_budget: int, timeout_seconds: int) -> dict[str, Any]:
    configure_runtime(root, token_budget=token_budget, timeout_seconds=timeout_seconds)

    from novel_agent.config import Config
    from novel_agent.main import run_novel_pipeline
    from novel_agent.memory.sql_store import NovelStore
    from novel_agent.models.model_settings import ModelSettingsStore
    from novel_agent.models.resolver import ModelResolver

    cfg = Config()
    cfg.ensure_dirs()
    store = NovelStore(cfg)
    resolver = ModelResolver(config=cfg, store=ModelSettingsStore(cfg))
    chat_route = resolver.resolve("creative")
    embedding_route = resolver.resolve("embedding")

    chat = resolver.chat("creative", temperature=0.0, streaming=False)
    await chat.ainvoke("Reply with exactly OK.")
    embedding = await resolver.embeddings().aembed_query("compatibility smoke")
    if not embedding:
        raise RuntimeError("embedding result was empty")

    args = argparse.Namespace(
        title="Compatibility Smoke",
        genre="speculative fiction",
        inspiration="A courier must return one lost letter before sunrise.",
        chapters=1,
        style="gu_long",
        auto=True,
        resume=None,
        feedback=None,
        scene_number=None,
        version_number=None,
    )
    captured = io.StringIO()
    with redirect_stdout(captured):
        await run_novel_pipeline(args, config=cfg, store=store)

    novels = store.list_novels()
    if len(novels) != 1:
        raise RuntimeError("workflow did not persist exactly one novel")
    chapters = store.get_all_chapters(str(novels[0]["id"]))
    if len(chapters) != 1:
        raise RuntimeError("workflow did not complete exactly one chapter")
    transitions = re.findall(r"\[节点完成\]\s*([^\r\n]+)", captured.getvalue())

    return {
        "status": "passed",
        "provider": chat_route.provider,
        "chat_model": chat_route.model_name,
        "embedding_model": embedding_route.model_name,
        "token_budget": token_budget,
        "checks": {"chat": "passed", "embedding": "passed", "workflow": "passed"},
        "workflow": {"chapters": len(chapters), "state_transitions": transitions},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the optional bounded real-model smoke test")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--token-budget", type=int, default=30_000)
    parser.add_argument("--timeout-seconds", type=int, default=1_200)
    args = parser.parse_args()
    if args.token_budget < 1 or args.timeout_seconds < 1:
        parser.error("budgets must be positive")
    return args


def main() -> int:
    args = parse_args()
    if not credentials_available():
        emit_report({"status": "skipped", "reason": "credentials_missing"}, args.report)
        return 2

    try:
        if args.runtime_root is not None:
            report = asyncio.run(
                asyncio.wait_for(
                    run_smoke(
                        args.runtime_root.resolve(),
                        token_budget=args.token_budget,
                        timeout_seconds=args.timeout_seconds,
                    ),
                    timeout=args.timeout_seconds,
                )
            )
        else:
            with tempfile.TemporaryDirectory(prefix="novel-agent-real-model-") as temp_dir:
                report = asyncio.run(
                    asyncio.wait_for(
                        run_smoke(
                            Path(temp_dir),
                            token_budget=args.token_budget,
                            timeout_seconds=args.timeout_seconds,
                        ),
                        timeout=args.timeout_seconds,
                    )
                )
    except BaseException as exc:
        emit_report({"status": "failed", "category": failure_category(exc)}, args.report)
        return 1

    emit_report(report, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
