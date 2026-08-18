"""小说导出工具:Markdown/TXT/DOCX/EPUB 与可恢复 ZIP 备份。"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from config import BASE_DIR
from memory.sql_store import NovelStore
from tools.backup_security import encrypt_backup

EXPORT_FORMATS = {"markdown", "txt", "docx", "epub", "backup"}


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", str(value or "小说")).strip(" .")
    return cleaned[:100] or "小说"


def _paragraph_xml(text: str, style: str = "") -> str:
    escaped = html.escape(text, quote=False)
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{style_xml}<w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'


def _export_metadata(novel: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, str]:
    source = {**novel, **(metadata or {})}
    title = str(source.get("title") or "小说").strip()
    return {
        "title": title,
        "author": str(source.get("author") or "未署名").strip(),
        "publisher": str(source.get("publisher") or "").strip(),
        "language": str(source.get("language") or "zh-CN").strip() or "zh-CN",
        "subject": str(source.get("subject") or source.get("genre") or "").strip(),
        "description": str(source.get("description") or source.get("inspiration") or "").strip(),
        "identifier": str(source.get("identifier") or source.get("id") or title).strip(),
        "date": str(source.get("date") or datetime.now(UTC).date().isoformat()).strip(),
    }


def _chapter_sections(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    sections = chapter.get("sections") or chapter.get("scenes") or []
    if isinstance(sections, list) and sections:
        normalized: list[dict[str, Any]] = []
        for index, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                continue
            content = str(section.get("content") or section.get("text") or "").strip()
            if not content:
                continue
            normalized.append({
                "title": str(section.get("title") or section.get("heading") or f"场景 {index}"),
                "content": content,
                "footnotes": section.get("footnotes") or [],
                "tables": section.get("tables") or [],
            })
        if normalized:
            return normalized
    return [{
        "title": "",
        "content": str(chapter.get("content", "")),
        "footnotes": chapter.get("footnotes") or [],
        "tables": chapter.get("tables") or [],
    }]


def _table_xml(table: Any) -> str:
    rows = table.get("rows") if isinstance(table, dict) else table
    if not isinstance(rows, list) or not rows:
        return ""
    cells = []
    for row in rows:
        values = list(row.values()) if isinstance(row, dict) else row
        if not isinstance(values, (list, tuple)):
            continue
        cells.append(
            "<w:tr>" + "".join(
                f"<w:tc>{_paragraph_xml(str(value))}</w:tc>" for value in values
            ) + "</w:tr>"
        )
    return "<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/></w:tblPr>" + "".join(cells) + "</w:tbl>"


def _footnote_xml(footnotes: Any) -> list[str]:
    if not isinstance(footnotes, list):
        return []
    return [
        _paragraph_xml(f"注 {index}: {item.get('text', item) if isinstance(item, dict) else item}", "FootnoteText")
        for index, item in enumerate(footnotes, start=1)
    ]


def _render_docx(
    metadata: dict[str, str],
    chapters: list[dict[str, Any]],
) -> bytes:
    parts = [
        _paragraph_xml(metadata["title"], "Title"),
        _paragraph_xml(metadata["author"], "Subtitle"),
    ]
    if metadata["publisher"]:
        parts.append(_paragraph_xml(metadata["publisher"], "Subtitle"))
    parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
    for chapter_index, chapter in enumerate(chapters):
        if chapter_index:
            parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        parts.append(_paragraph_xml(
            f"第{chapter.get('chapter_number', 0)}章 {chapter.get('title') or ''}",
            "Heading1",
        ))
        for section in _chapter_sections(chapter):
            if section["title"]:
                parts.append(_paragraph_xml(section["title"], "Heading2"))
            parts.extend(
                _paragraph_xml(line)
                for line in section["content"].splitlines() or [""]
            )
            parts.extend(_table_xml(table) for table in section["tables"] if _table_xml(table))
            parts.extend(_footnote_xml(section["footnotes"]))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(parts)}<w:sectPr/></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '</Relationships>'
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )
    styles = "".join([
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
        '<w:docDefaults><w:rPrDefault><w:rPr>',
        '<w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="等线"/>',
        '</w:rPr></w:rPrDefault></w:docDefaults>',
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">',
        '<w:name w:val="Normal"/><w:pPr><w:spacing w:after="180" w:line="360" w:lineRule="auto"/>',
        '</w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>',
        '<w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:pPr><w:jc w:val="center"/>',
        '<w:spacing w:after="260"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/>',
        '<w:rPr><w:color w:val="666666"/><w:sz w:val="22"/></w:rPr>',
        '<w:pPr><w:jc w:val="center"/><w:spacing w:after="140"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>',
        '<w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:pPr><w:keepNext/>',
        '<w:pageBreakBefore w:val="0"/><w:spacing w:before="300" w:after="180"/>',
        '</w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>',
        '<w:rPr><w:b/><w:sz w:val="24"/></w:rPr><w:pPr><w:keepNext/>',
        '<w:spacing w:before="220" w:after="120"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="FootnoteText"><w:name w:val="footnote text"/>',
        '<w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr></w:style>',
        '</w:styles>',
    ])
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
        f'<dc:title>{html.escape(metadata["title"])}</dc:title>'
        f'<dc:creator>{html.escape(metadata["author"])}</dc:creator>'
        f'<dc:subject>{html.escape(metadata["subject"])}</dc:subject>'
        f'<dcterms:created>{html.escape(metadata["date"])}</dcterms:created>'
        '</cp:coreProperties>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("word/styles.xml", styles)
        archive.writestr("docProps/core.xml", core)
    return output.getvalue()


def _epub_table(table: Any) -> str:
    rows = table.get("rows") if isinstance(table, dict) else table
    if not isinstance(rows, list) or not rows:
        return ""
    rendered: list[str] = []
    for row in rows:
        values = list(row.values()) if isinstance(row, dict) else row
        if not isinstance(values, (list, tuple)):
            continue
        rendered.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value), quote=False)}</td>" for value in values
            ) + "</tr>"
        )
    return f'<table>{"".join(rendered)}</table>' if rendered else ""


def _epub_footnotes(footnotes: Any, prefix: str) -> str:
    if not isinstance(footnotes, list) or not footnotes:
        return ""
    items = []
    for index, item in enumerate(footnotes, start=1):
        text = item.get("text", item) if isinstance(item, dict) else item
        items.append(
            f'<aside epub:type="footnote" id="{prefix}-note-{index}">'
            f'<p><sup>{index}</sup> {html.escape(str(text), quote=False)}</p></aside>'
        )
    return f'<section class="footnotes"><h2>注释</h2>{"".join(items)}</section>'


def _svg_cover(metadata: dict[str, str]) -> str:
    title = html.escape(metadata["title"])
    author = html.escape(metadata["author"])
    subject = html.escape(metadata["subject"])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2560" viewBox="0 0 1600 2560">'
        '<rect width="1600" height="2560" fill="#23352f"/>'
        '<rect x="110" y="110" width="1380" height="2340" fill="none" stroke="#d2b779" stroke-width="8"/>'
        '<text x="800" y="1050" text-anchor="middle" fill="#f7f2e7" font-size="118" font-family="serif">'
        f'{title}</text>'
        '<text x="800" y="1250" text-anchor="middle" fill="#d2b779" font-size="52" font-family="sans-serif">'
        f'{subject}</text>'
        '<text x="800" y="2120" text-anchor="middle" fill="#f7f2e7" font-size="62" font-family="serif">'
        f'{author}</text></svg>'
    )


def _render_epub(metadata: dict[str, str], chapters: list[dict[str, Any]]) -> bytes:
    identifier = html.escape(metadata["identifier"])
    manifest: list[str] = []
    spine: list[str] = []
    pages: list[tuple[str, str]] = []
    nav_items: list[str] = []
    ncx_points: list[str] = []
    play_order = 1
    for index, chapter in enumerate(chapters, start=1):
        chapter_play_order = play_order
        play_order += 1
        item_id = f"chapter-{index}"
        href = f"chapter-{index}.xhtml"
        manifest.append(f'<item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{item_id}"/>')
        chapter_title = html.escape(str(chapter.get("title") or ""))
        heading = f"第{chapter.get('chapter_number', index)}章 {chapter.get('title') or ''}"
        sections = _chapter_sections(chapter)
        nested_nav: list[str] = []
        body = [f"<h1>{html.escape(heading, quote=False)}</h1>"]
        section_points: list[str] = []
        for section_index, section in enumerate(sections, start=1):
            section_id = f"section-{section_index}"
            if section["title"]:
                escaped_title = html.escape(section["title"])
                body.append(f'<section id="{section_id}"><h2>{escaped_title}</h2>')
                nested_nav.append(f'<li><a href="{href}#{section_id}">{escaped_title}</a></li>')
                section_play_order = play_order
                play_order += 1
                section_points.append(
                    f'<navPoint id="nav-{index}-{section_index}" playOrder="{section_play_order}">'
                    f'<navLabel><text>{escaped_title}</text></navLabel>'
                    f'<content src="{href}#{section_id}"/></navPoint>'
                )
            for line in section["content"].splitlines() or [""]:
                body.append(f"<p>{html.escape(line, quote=False)}</p>")
            body.extend(_epub_table(table) for table in section["tables"] if _epub_table(table))
            body.append(_epub_footnotes(section["footnotes"], f"chapter-{index}-{section_index}"))
            if section["title"]:
                body.append("</section>")
        chapter_label = f"第{chapter.get('chapter_number', index)}章 {chapter_title}"
        nav_items.append(
            f'<li><a href="{href}">{chapter_label}</a>'
            f'{"<ol>" + "".join(nested_nav) + "</ol>" if nested_nav else ""}</li>'
        )
        ncx_points.append(
            f'<navPoint id="nav-{index}" playOrder="{chapter_play_order}">'
            f'<navLabel><text>{chapter_label}</text></navLabel><content src="{href}"/>'
            f'{"".join(section_points)}</navPoint>'
        )
        pages.append((href, "".join(body)))
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">'
        f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="book-id">{identifier}</dc:identifier>'
        f'<dc:title>{html.escape(metadata["title"])}</dc:title>'
        f'<dc:creator>{html.escape(metadata["author"])}</dc:creator>'
        f'<dc:language>{html.escape(metadata["language"])}</dc:language>'
        f'<dc:publisher>{html.escape(metadata["publisher"])}</dc:publisher>'
        f'<dc:subject>{html.escape(metadata["subject"])}</dc:subject>'
        f'<dc:description>{html.escape(metadata["description"])}</dc:description>'
        f'<dc:date>{html.escape(metadata["date"])}</dc:date>'
        f'<meta property="dcterms:modified">{html.escape(metadata["date"])}T00:00:00Z</meta></metadata>'
        f'<manifest><item id="nav" properties="nav" href="nav.xhtml" '
        f'media-type="application/xhtml+xml"/>'
        f'<item id="cover-image" properties="cover-image" href="cover.svg" media-type="image/svg+xml"/>'
        f'<item id="cover-page" href="cover.xhtml" media-type="application/xhtml+xml"/>'
        f'<item id="css" href="styles.css" media-type="text/css"/>'
        f'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        f'{"".join(manifest)}</manifest>'
        f'<spine toc="ncx">{"".join(spine)}</spine></package>'
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
        f'<title>{html.escape(metadata["title"])}</title><link rel="stylesheet" href="styles.css"/>'
        '</head><body><nav epub:type="toc"><h1>目录</h1>'
        f'<ol>{"".join(nav_items)}</ol></nav></body></html>'
    )
    ncx = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{identifier}"/></head>'
        f'<docTitle><text>{html.escape(metadata["title"])}</text></docTitle>'
        f'<navMap>{"".join(ncx_points)}</navMap></ncx>'
    )
    css = (
        'body{font-family:serif;line-height:1.8;margin:6%;color:#242b27}'
        'h1{font-size:1.8em;margin:2em 0 1em;page-break-before:always}'
        'h2{font-size:1.25em;margin:1.6em 0 .8em}'
        'p{text-indent:2em;margin:.45em 0}'
        'table{width:100%;border-collapse:collapse;margin:1em 0}'
        'td,th{border:1px solid #888;padding:.35em}'
        '.footnotes{border-top:1px solid #aaa;margin-top:2em;font-size:.85em}'
        '.cover{margin:0;text-align:center}.cover img{max-width:100%;height:auto}'
    )
    cover_page = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        f'<title>{html.escape(metadata["title"])}</title><link rel="stylesheet" href="styles.css"/>'
        '</head><body class="cover"><img src="cover.svg" alt="封面"/></body></html>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/nav.xhtml", nav)
        archive.writestr("OEBPS/toc.ncx", ncx)
        archive.writestr("OEBPS/styles.css", css)
        archive.writestr("OEBPS/cover.svg", _svg_cover(metadata))
        archive.writestr("OEBPS/cover.xhtml", cover_page)
        for href, page in pages:
            page_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head>'
                f'<title>{html.escape(metadata["title"])}</title><link rel="stylesheet" href="styles.css"/>'
                f'</head><body>{page}</body></html>'
            )
            archive.writestr(f"OEBPS/{href}", page_xml)
    return output.getvalue()


def _render_backup(
    novel: dict[str, Any],
    chapters: list[dict[str, Any]],
    *,
    progress: dict[str, Any] | None = None,
    memory_snapshots: list[dict[str, Any]] | None = None,
    memory_quality_runs: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> bytes:
    manifest = {
        "schema_version": "novel-agent-backup-v2",
        "created_at": datetime.now(UTC).isoformat(),
        "novel_id": novel.get("id", ""),
        "chapter_count": len(chapters),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        files: dict[str, str] = {
            "novel.json": json.dumps(novel, ensure_ascii=False, indent=2, default=str),
            "progress.json": json.dumps(progress or {}, ensure_ascii=False, indent=2, default=str),
            "memory_snapshots.json": json.dumps(
                memory_snapshots or [], ensure_ascii=False, indent=2, default=str
            ),
            "memory_quality_runs.json": json.dumps(
                memory_quality_runs or [], ensure_ascii=False, indent=2, default=str
            ),
        }
        if checkpoint:
            files["checkpoint.json"] = json.dumps(
                checkpoint, ensure_ascii=False, indent=2, default=str
            )
        for index, chapter in enumerate(chapters, start=1):
            files[f"chapters/{index:04d}.json"] = json.dumps(
                chapter, ensure_ascii=False, indent=2, default=str
            )
        manifest["checksums"] = {
            path: hashlib.sha256(payload.encode("utf-8")).hexdigest()
            for path, payload in files.items()
        }
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        )
        for path, payload in files.items():
            archive.writestr(path, payload)
    return output.getvalue()


def export_novel_bytes(
    novel: dict[str, Any],
    chapters: list[dict[str, Any]],
    fmt: str,
    *,
    progress: dict[str, Any] | None = None,
    memory_snapshots: list[dict[str, Any]] | None = None,
    memory_quality_runs: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
    password: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str, bytes]:
    normalized = str(fmt or "markdown").casefold()
    normalized = {"md": "markdown", "zip": "backup"}.get(normalized, normalized)
    if normalized not in {"markdown", "txt", "docx", "epub", "backup"}:
        raise ValueError(f"不支持的导出格式:{fmt}")
    publication = _export_metadata(novel, metadata)
    title = publication["title"]
    if normalized == "markdown":
        parts = [
            f"# {title}",
            "",
            f"> 作者:{publication['author']} | 类型:{novel.get('genre', '')} | 共 {len(chapters)} 章",
            "",
        ]
        for chapter in chapters:
            heading = f"## 第{chapter.get('chapter_number', 0)}章 {chapter.get('title') or ''}"
            parts += [heading, "", str(chapter.get("content", "")), ""]
        return f"{_safe_filename(title)}.md", "text/markdown; charset=utf-8", "\n".join(parts).encode("utf-8")
    if normalized == "txt":
        parts = [title, "=" * 40, ""]
        for chapter in chapters:
            heading = f"第{chapter.get('chapter_number', 0)}章 {chapter.get('title') or ''}"
            parts += [heading, "", str(chapter.get("content", "")), ""]
        return f"{_safe_filename(title)}.txt", "text/plain; charset=utf-8", "\n".join(parts).encode("utf-8")
    if normalized == "docx":
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return f"{_safe_filename(title)}.docx", media, _render_docx(publication, chapters)
    if normalized == "epub":
        return f"{_safe_filename(title)}.epub", "application/epub+zip", _render_epub(publication, chapters)
    payload = _render_backup(
        novel,
        chapters,
        progress=progress,
        memory_snapshots=memory_snapshots,
        memory_quality_runs=memory_quality_runs,
        checkpoint=checkpoint,
    )
    if password:
        return (
            f"{_safe_filename(title)}.novel-backup.enc",
            "application/octet-stream",
            encrypt_backup(payload, password),
        )
    return f"{_safe_filename(title)}.novel-backup.zip", "application/zip", payload


@tool
def export_to_format(novel_id: str, format: str = "markdown") -> str:
    """将小说导出为指定格式文件,返回导出路径。"""
    store = NovelStore()
    novel = store.get_novel(novel_id)
    if not novel:
        return f"小说 {novel_id} 不存在,导出失败。"
    chapters = store.get_all_chapters(novel_id)
    filename, _, payload = export_novel_bytes(
        novel,
        chapters,
        format,
        progress=store.get_progress(novel_id),
        memory_snapshots=store.list_memory_snapshots(novel_id),
        memory_quality_runs=store.list_memory_quality_runs(novel_id),
    )
    out_dir = BASE_DIR / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{Path(filename).stem}_{stamp}{Path(filename).suffix}"
    path.write_bytes(payload)
    return f"已导出:{path}"
