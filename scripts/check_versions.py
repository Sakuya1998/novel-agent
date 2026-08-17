"""查询核心依赖在 PyPI 的最新稳定版(排除预发布)。"""

import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

PACKAGES = [
    "langgraph", "langgraph-checkpoint-sqlite", "langchain", "langchain-openai", "langchain-anthropic",
    "langchain-chroma", "chromadb", "fastapi", "uvicorn",
    "python-dotenv", "pydantic", "pydantic-settings", "pyyaml",
    "pytest", "pytest-asyncio", "httpx", "ruff",
]


def main() -> None:
    for pkg in PACKAGES:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", pkg],
            capture_output=True, text=True,
        )
        out = proc.stdout + proc.stderr
        m = re.search(r"Available versions:\s*([^\s(]+)", out)
        try:
            installed = version(pkg)
        except PackageNotFoundError:
            installed = "-"
        print(f"{pkg}=={m.group(1) if m else '?'} (installed: {installed})")


if __name__ == "__main__":
    main()
