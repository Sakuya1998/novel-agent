"""Launch an isolated API instance for deterministic browser tests."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def configure_environment(runtime_root: Path) -> None:
    runtime_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "SQLITE_DB_PATH": runtime_root / "novels.db",
        "CHECKPOINT_DB_PATH": runtime_root / "checkpoints.db",
        "CHROMA_PERSIST_DIR": runtime_root / "chroma",
        "MODEL_SECRET_KEY_PATH": runtime_root / "model-settings.key",
        "TRANSFER_DIR": runtime_root / "transfers",
        "RUNTIME_BACKUP_DIR": runtime_root / "runtime-backups",
    }
    os.environ.update(
        {
            "APP_ENVIRONMENT": "test",
            "AUTH_ENABLED": "true",
            "AUTH_COOKIE_SECURE": "false",
            "FRONTEND_ORIGINS": "http://127.0.0.1:4173",
            "OPENAI_API_KEY": "e2e-readiness-key",
            **{name: str(path) for name, path in paths.items()},
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    configure_environment(args.root.resolve())

    import uvicorn

    uvicorn.run("novel_agent.api.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
