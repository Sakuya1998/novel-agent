"""导入、备份与出版格式导出测试。"""

import io
import json
import re
import zipfile

import pytest

import tools.import_tools as import_tools
from tools.export_tools import export_novel_bytes
from tools.import_tools import parse_import_bytes
from tools.memory_quality import rebuild_memory_index


def _novel():
    return {
        "id": "n1",
        "title": "雾中剑",
        "genre": "武侠",
        "inspiration": "失忆剑客",
        "style": "gu_long",
        "total_chapters": 2,
    }


def _chapters():
    return [
        {"chapter_number": 1, "title": "雾起", "content": "林寒进入雾都。", "summary": "林寒进入雾都"},
        {"chapter_number": 2, "title": "追兵", "content": "城门外传来马蹄。", "summary": "追兵出现"},
    ]


def test_publication_exports_have_expected_container_signatures():
    novel, chapters = _novel(), _chapters()
    _, _, markdown = export_novel_bytes(novel, chapters, "markdown")
    assert markdown.startswith(b"# ")
    for fmt, expected in [("docx", b"word/document.xml"), ("epub", b"mimetype"), ("backup", b"manifest.json")]:
        _, _, payload = export_novel_bytes(novel, chapters, fmt)
        assert expected in payload or (fmt == "docx" and b"PK" in payload)


def test_publication_exports_include_metadata_cover_styles_and_nested_toc():
    novel = {**_novel(), "inspiration": "一段出版简介"}
    chapters = [{
        "chapter_number": 1,
        "title": "雾起",
        "content": "正文不会丢失",
        "sections": [{
            "title": "场景一：城门",
            "content": "林寒进入雾都。",
            "footnotes": [{"text": "地名注释"}],
            "tables": [[["角色", "状态"], ["林寒", "紧张"]]],
        }],
    }]
    _, _, docx = export_novel_bytes(
        novel,
        chapters,
        "docx",
        metadata={"author": "作者甲", "publisher": "出版社乙"},
    )
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        document = archive.read("word/document.xml").decode()
        styles = archive.read("word/styles.xml").decode()
        core = archive.read("docProps/core.xml").decode()
    assert "Heading2" in document
    assert "TableGrid" in document
    assert "注 1" in document
    assert "作者甲" in core and "出版社乙" not in core
    assert "Heading2" in styles and "FootnoteText" in styles

    epub_name, _, epub = export_novel_bytes(
        novel,
        chapters,
        "epub",
        metadata={"author": "作者甲", "publisher": "出版社乙"},
    )
    with zipfile.ZipFile(io.BytesIO(epub)) as archive:
        opf = archive.read("OEBPS/content.opf").decode()
        nav = archive.read("OEBPS/nav.xhtml").decode()
        ncx = archive.read("OEBPS/toc.ncx").decode()
        cover = archive.read("OEBPS/cover.svg").decode()
    assert "作者甲" in opf and "出版社乙" in opf
    assert "cover-image" in opf and "cover.svg" in opf
    assert "场景一：城门" in nav and "<ol>" in nav
    assert "场景一：城门" in ncx
    play_orders = [int(value) for value in re.findall(r'playOrder="(\d+)"', ncx)]
    assert play_orders == list(range(1, len(play_orders) + 1))
    assert "雾中剑" in cover
    parsed = parse_import_bytes(epub, epub_name)
    assert [item["chapter_number"] for item in parsed["chapters"]] == [1]


def test_markdown_docx_epub_and_backup_roundtrip_to_chapters():
    novel, chapters = _novel(), _chapters()
    markdown_name, _, markdown = export_novel_bytes(novel, chapters, "markdown")
    parsed_markdown = parse_import_bytes(markdown, markdown_name)
    assert parsed_markdown["novel"]["title"] == novel["title"]
    assert [item["chapter_number"] for item in parsed_markdown["chapters"]] == [1, 2]

    docx_name, _, docx = export_novel_bytes(novel, chapters, "docx")
    assert [item["chapter_number"] for item in parse_import_bytes(docx, docx_name)["chapters"]] == [1, 2]

    epub_name, _, epub = export_novel_bytes(novel, chapters, "epub")
    assert [item["chapter_number"] for item in parse_import_bytes(epub, epub_name)["chapters"]] == [1, 2]

    backup_name, _, backup = export_novel_bytes(novel, chapters, "backup", progress={"state": {"canon": {}}})
    restored = parse_import_bytes(backup, backup_name)
    assert restored["novel"]["id"] == "n1"
    assert restored["chapters"][1]["content"] == chapters[1]["content"]


def test_backup_v2_roundtrip_preserves_checkpoint_payload():
    novel, chapters = _novel(), _chapters()
    _, _, backup = export_novel_bytes(
        novel,
        chapters,
        "backup",
        checkpoint={
            "schema_version": "langgraph-checkpoint-v1",
            "state": {"novel_id": "n1", "current_phase": "human_review"},
            "next": ["human_review"],
        },
    )
    restored = parse_import_bytes(backup, "book.novel-backup.zip")
    assert restored["checkpoint"]["next"] == ["human_review"]
    assert restored["checkpoint"]["state"]["current_phase"] == "human_review"


def test_password_encrypted_backup_roundtrip_and_wrong_password_rejection():
    filename, media_type, encrypted = export_novel_bytes(
        _novel(),
        _chapters(),
        "backup",
        password="correct horse battery staple",
    )
    assert filename.endswith(".novel-backup.enc")
    assert media_type == "application/octet-stream"
    assert not encrypted.startswith(b"PK")
    restored = parse_import_bytes(encrypted, filename, password="correct horse battery staple")
    assert restored["novel"]["title"] == "雾中剑"
    with pytest.raises(ValueError, match="密码错误"):
        parse_import_bytes(encrypted, filename, password="wrong password")
    with pytest.raises(ValueError, match="提供密码"):
        parse_import_bytes(encrypted, filename)


def test_backup_checksum_rejects_tampered_payload():
    _, _, backup = export_novel_bytes(_novel(), _chapters(), "backup")
    source = io.BytesIO(backup)
    output = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w") as rewritten:
        for info in original.infolist():
            payload = original.read(info.filename)
            if info.filename == "chapters/0001.json":
                payload = payload.replace("林寒进入雾都".encode(), "被篡改的正文".encode())
            rewritten.writestr(info, payload)
    with pytest.raises(ValueError, match="校验失败"):
        parse_import_bytes(output.getvalue(), "tampered.novel-backup.zip")


def test_backup_rejects_path_traversal_member():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": "novel-agent-backup-v1"}))
        archive.writestr("novel.json", json.dumps(_novel()))
        archive.writestr("../escape.json", "{}")
    with pytest.raises(ValueError, match="非法路径"):
        parse_import_bytes(output.getvalue(), "unsafe.novel-backup.zip")


def test_archive_import_rejects_excessive_uncompressed_size(monkeypatch):
    monkeypatch.setattr(import_tools, "MAX_ARCHIVE_TOTAL_BYTES", 100)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * 101)
    with pytest.raises(ValueError, match="解压后总大小超过限制"):
        parse_import_bytes(output.getvalue(), "oversized.docx")


class _FailingMemory:
    def __init__(self):
        self.records = [{"id": "old", "content": "旧索引", "metadata": {"type": "chapter"}}]
        self.fail = False

    def list_records(self):
        return list(self.records)

    def clear(self):
        self.records = []

    def store_content(self, content, metadata=None, content_id=None):
        if self.fail and content_id == "new-2":
            raise RuntimeError("embedding unavailable")
        self.records.append({"id": content_id, "content": content, "metadata": metadata or {}})


def test_memory_rebuild_rolls_back_when_a_write_fails():
    memory = _FailingMemory()
    memory.fail = True
    try:
        rebuild_memory_index(memory, [
            {"id": "new-1", "content": "新一", "metadata": {}},
            {"id": "new-2", "content": "新二", "metadata": {}},
        ])
    except RuntimeError as exc:
        assert "embedding unavailable" in str(exc)
    else:
        raise AssertionError("expected rebuild failure")
    assert [item["id"] for item in memory.records] == ["old"]
