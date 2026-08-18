"""运行时备份命令: python -m scripts.runtime_backup create|verify。"""

from __future__ import annotations

import argparse
import json

from tools.runtime_backup import create_runtime_backup, restore_runtime_backup, verify_runtime_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Novel Agent 运行时 SQLite/checkpoint/密钥备份")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--password", default="", help="可选的 AES-GCM 备份密码")
    create.add_argument("--output-dir", default="", help="备份输出目录")
    create.add_argument("--keep", type=int, default=None, help="保留最近多少份备份")
    create.add_argument("--confirm-stopped", action="store_true", help="确认 API 已停止")
    verify = subparsers.add_parser("verify")
    verify.add_argument("path")
    verify.add_argument("--password", default="")
    restore = subparsers.add_parser("restore")
    restore.add_argument("path")
    restore.add_argument("--password", default="")
    restore.add_argument("--confirm", action="store_true", help="确认 API 已停止并覆盖运行时文件")
    args = parser.parse_args()
    if args.command == "create":
        result = create_runtime_backup(
            output_dir=args.output_dir or None,
            password=args.password,
            retention_count=args.keep,
            confirm_stopped=args.confirm_stopped,
        )
    elif args.command == "verify":
        result = {"manifest": verify_runtime_backup(args.path, args.password)}
    else:
        result = restore_runtime_backup(args.path, password=args.password, confirm=args.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
