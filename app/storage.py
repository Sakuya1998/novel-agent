"""项目存储:每个小说项目一个 JSON 文件,原子写入 + 异步锁。

生产增强:
- pid 白名单校验,杜绝路径穿越;
- 唯一临时文件名,多进程/多实例写入互不踩踏;
- 文件损坏时移入 corrupt/ 备份并显式报错,绝不把损坏当「不存在」;
- 读写失败显式抛 StorageError,由全局异常处理器兜底。
"""

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .core.exceptions import NotFoundError, StorageError

logger = logging.getLogger("novel.storage")

_PID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

SCHEMA_VERSION = 1


def _now() -> float:
    return time.time()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_guard = threading.Lock()

    # ---------- 内部工具 ----------
    def _check_pid(self, pid: str) -> None:
        if not _PID_RE.fullmatch(pid or ""):
            # 非法 ID 与「不存在」同样返回 404,不泄漏校验规则
            raise NotFoundError("项目不存在")

    def _lock(self, pid: str) -> asyncio.Lock:
        with self._lock_guard:
            if pid not in self._locks:
                self._locks[pid] = asyncio.Lock()
            return self._locks[pid]

    def _pfile(self, pid: str) -> Path:
        self._check_pid(pid)
        return self.root / f"{pid}.json"

    def _quarantine_corrupt(self, pid: str, f: Path) -> None:
        """把损坏文件移入 corrupt/ 目录,保留现场供排查。"""
        try:
            qdir = self.root / "corrupt"
            qdir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            f.replace(qdir / f"{f.stem}-{stamp}.json")
            logger.error("项目文件损坏,已隔离 pid=%s file=%s", pid, f.name)
        except OSError:
            logger.exception("隔离损坏文件失败 pid=%s", pid, exc_info=True)

    # ---------- 项目 ----------
    def blank_project(self, title: str = "", idea: str = "", genre: str = "") -> dict[str, Any]:
        return {
            "id": uuid.uuid4().hex[:12],
            "schema_version": SCHEMA_VERSION,
            "title": title.strip() or "未命名小说",
            "idea": idea,
            "genre": genre,
            "premise": "",
            "characters": [],  # [{name,role,appearance,personality,background,goal,arc,relationships}]
            "outline": [],  # [{index,title,summary,key_events}]
            "chapters": [],  # [{index,title,content,summary,updated_at}]
            "created_at": _now(),
            "updated_at": _now(),
        }

    def create_project(self, title: str, idea: str = "", genre: str = "") -> dict[str, Any]:
        p = self.blank_project(title, idea, genre)
        self.save_project(p)
        return p

    def get_project(self, pid: str) -> dict[str, Any] | None:
        f = self._pfile(pid)
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._quarantine_corrupt(pid, f)
            raise StorageError(f"项目数据损坏(pid={pid}),原文件已备份至 corrupt/ 目录") from None
        except OSError as e:
            raise StorageError(f"读取项目失败:{e}") from e
        if not isinstance(data, dict) or "id" not in data:
            self._quarantine_corrupt(pid, f)
            raise StorageError(f"项目数据结构非法(pid={pid}),原文件已备份至 corrupt/ 目录")
        return data

    def save_project(self, project: dict[str, Any]) -> None:
        project.setdefault("schema_version", SCHEMA_VERSION)
        project["updated_at"] = _now()
        f = self._pfile(project["id"])
        # 唯一临时文件名:即使多进程同时写同一项目也不会互相覆盖 tmp
        tmp = f.with_name(f"{f.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(f)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise StorageError(f"保存项目失败:{e}") from e

    async def update_project(self, pid: str, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """加锁读取-修改-保存,返回更新后的项目。mutator 抛异常则不落盘。

        项目不存在/被并发删除时抛 NotFoundError(AppError 子类):
        非流式路由经全局异常处理器返回 404,流式生成器兜底为可读的 error 事件。
        """
        self._check_pid(pid)
        async with self._lock(pid):
            p = self.get_project(pid)
            if p is None:
                raise NotFoundError("项目不存在")
            mutator(p)
            self.save_project(p)
            return p

    def delete_project(self, pid: str) -> bool:
        f = self._pfile(pid)
        if f.exists():
            try:
                f.unlink()
            except OSError as e:
                raise StorageError(f"删除项目失败:{e}") from e
            return True
        return False

    def list_projects(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for f in self.root.glob("*.json"):
            if f.name == "config.json":
                continue
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                items.append(
                    {
                        "id": p.get("id", f.stem),
                        "title": p.get("title", "未命名小说"),
                        "genre": p.get("genre", ""),
                        "chapter_count": len(p.get("chapters", [])),
                        "outline_count": len(p.get("outline", [])),
                        "updated_at": p.get("updated_at", 0),
                    }
                )
            except Exception:
                logger.warning("列表扫描:跳过无法解析的文件 %s", f.name)
                continue
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    # ---------- 运维 ----------
    def healthcheck(self) -> bool:
        """数据目录可写探针(readyz 使用)。"""
        try:
            probe = self.root / ".healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False
