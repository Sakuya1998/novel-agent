"""导出工具(文档 6.1):将小说导出为 Markdown/TXT。"""

from datetime import datetime

from langchain_core.tools import tool

from config import BASE_DIR
from memory.sql_store import NovelStore


@tool
def export_to_format(novel_id: str, format: str = "markdown") -> str:
    """将小说导出为指定格式文件,返回导出路径。

    Args:
        novel_id: 小说 ID
        format: 导出格式,markdown(默认)或 txt
    """
    store = NovelStore()
    novel = store.get_novel(novel_id)
    if not novel:
        return f"小说 {novel_id} 不存在,导出失败。"

    chapters = store.get_all_chapters(novel_id)
    fmt = format.lower()
    ext = "md" if fmt == "markdown" else "txt"

    if fmt == "markdown":
        parts = [f"# {novel['title']}", "", f"> 类型:{novel.get('genre', '')} | 共 {len(chapters)} 章", ""]
        for ch in chapters:
            parts += [f"## 第{ch['chapter_number']}章 {ch['title'] or ''}", "", ch["content"] or "", ""]
    else:
        parts = [novel["title"], "=" * 40, ""]
        for ch in chapters:
            parts += [f"第{ch['chapter_number']}章 {ch['title'] or ''}", "", ch["content"] or "", ""]

    out_dir = BASE_DIR / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{novel['title']}_{stamp}.{ext}"
    path.write_text("\n".join(parts), encoding="utf-8")
    return f"已导出:{path}"
