"""项目存储:每个小说项目一个 JSON 文件,原子写入。"""
import asyncio
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _now() -> float:
    return time.time()


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._lock_guard = threading.Lock()

    def _lock(self, pid: str) -> asyncio.Lock:
        with self._lock_guard:
            if pid not in self._locks:
                self._locks[pid] = asyncio.Lock()
            return self._locks[pid]

    def _pfile(self, pid: str) -> Path:
        return self.root / f"{pid}.json"

    # ---------- 项目 ----------
    def blank_project(self, title: str = "", idea: str = "", genre: str = "") -> Dict[str, Any]:
        return {
            "id": uuid.uuid4().hex[:12],
            "title": title.strip() or "未命名小说",
            "idea": idea,
            "genre": genre,
            "premise": "",
            "characters": [],
            "outline": [],   # [{index,title,summary,key_events}]
            "chapters": [],  # [{index,title,content,summary,updated_at}]
            "created_at": _now(),
            "updated_at": _now(),
        }

    def create_project(self, title: str, idea: str = "", genre: str = "") -> Dict[str, Any]:
        p = self.blank_project(title, idea, genre)
        self.save_project(p)
        return p

    def get_project(self, pid: str) -> Optional[Dict[str, Any]]:
        f = self._pfile(pid)
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_project(self, project: Dict[str, Any]) -> None:
        project["updated_at"] = _now()
        f = self._pfile(project["id"])
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)

    async def update_project(self, pid: str, mutator: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        """加锁读取-修改-保存,返回更新后的项目。"""
        async with self._lock(pid):
            p = self.get_project(pid)
            if p is None:
                raise KeyError("项目不存在")
            mutator(p)
            self.save_project(p)
            return p

    def delete_project(self, pid: str) -> bool:
        f = self._pfile(pid)
        if f.exists():
            f.unlink()
            return True
        return False

    def list_projects(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
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
                continue
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items
