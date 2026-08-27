"""Compatibility launcher for the packaged Novel Agent CLI."""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

def main() -> None:
    from novel_agent.main import main as packaged_main

    packaged_main()


if __name__ == "__main__":
    main()
