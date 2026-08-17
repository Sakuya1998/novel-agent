"""基于 SQLite 的结构化存储(文档 5.3)。

NovelStore:小说元数据、章节内容、创作进度的持久化。
作为向量记忆的补充,支持精确查询与导出。
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from config import Config


class NovelStore:
    """SQLite 持久化存储,管理小说/章节/进度三类记录。"""

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.config.ensure_dirs()
        self.db_path = Path(self.config.sqlite_db_path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS novels (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    genre TEXT,
                    inspiration TEXT,
                    style TEXT,
                    total_chapters INTEGER DEFAULT 10,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    novel_id TEXT,
                    chapter_number INTEGER,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    word_count INTEGER,
                    status TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id),
                    UNIQUE(novel_id, chapter_number)
                );

                CREATE TABLE IF NOT EXISTS progress (
                    novel_id TEXT PRIMARY KEY,
                    current_chapter INTEGER,
                    current_phase TEXT,
                    state_json TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (novel_id) REFERENCES novels(id)
                );
                """
            )

    # ------------------------------------------------------------------
    # 小说
    # ------------------------------------------------------------------
    def create_novel(
        self,
        novel_id: str,
        title: str,
        genre: str = "",
        style: str = "",
        total_chapters: int = 10,
        inspiration: str = "",
    ) -> dict:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO novels (id, title, genre, inspiration, style, total_chapters, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (novel_id, title, genre, inspiration, style, total_chapters, now, now),
            )
        return {"id": novel_id, "title": title, "genre": genre, "inspiration": inspiration,
                "style": style, "total_chapters": total_chapters,
                "created_at": now, "updated_at": now}

    def get_novel(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
        return dict(row) if row else None

    def list_novels(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM novels ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_novel(self, novel_id: str) -> bool:
        """删除作品及其章节、进度记录;返回是否确实删除了一部作品。"""
        with self._conn() as conn:
            exists = conn.execute("SELECT 1 FROM novels WHERE id = ?", (novel_id,)).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM progress WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
            return True

    # ------------------------------------------------------------------
    # 章节
    # ------------------------------------------------------------------
    def save_chapter(
        self,
        novel_id: str,
        chapter_number: int,
        title: str,
        content: str,
        summary: str = "",
        status: str = "draft",
    ) -> int:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO chapters (novel_id, chapter_number, title, content, summary,
                                      word_count, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(novel_id, chapter_number) DO UPDATE SET
                    title=excluded.title, content=excluded.content, summary=excluded.summary,
                    word_count=excluded.word_count, status=excluded.status, updated_at=excluded.updated_at
                """,
                (novel_id, chapter_number, title, content, summary,
                 len(content), status, now, now),
            )
            row = conn.execute(
                "SELECT id FROM chapters WHERE novel_id = ? AND chapter_number = ?",
                (novel_id, chapter_number),
            ).fetchone()
            return int(row["id"]) if row else 0

    def get_chapter(self, novel_id: str, chapter_number: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? AND chapter_number = ?",
                (novel_id, chapter_number),
            ).fetchone()
        return dict(row) if row else None

    def get_all_chapters(self, novel_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? ORDER BY chapter_number",
                (novel_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 进度(含 LangGraph 状态快照)
    # ------------------------------------------------------------------
    def save_progress(
        self, novel_id: str, current_chapter: int, current_phase: str, state: dict | None = None
    ) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO progress (novel_id, current_chapter, current_phase, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(novel_id) DO UPDATE SET
                    current_chapter=excluded.current_chapter,
                    current_phase=excluded.current_phase,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (novel_id, current_chapter, current_phase,
                 json.dumps(state, ensure_ascii=False, default=str) if state else None, now),
            )

    def get_progress(self, novel_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM progress WHERE novel_id = ?", (novel_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["state"] = json.loads(d.pop("state_json") or "{}")
        return d
