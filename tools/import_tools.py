"""小说文本、DOCX、EPUB 与 Novel Agent 备份导入解析。"""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from tools.backup_security import decrypt_backup, is_encrypted_backup

CHAPTER_RE = re.compile(r"^\s*(?:#{1,3}\s*)?第\s*(\d+)\s*章\s*(?:[：:、.\-]\s*|\s*)(.*)$")
MAX_ARCHIVE_MEMBERS = 2048
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 200


def _validate_archive_limits(archive: zipfile.ZipFile) -> None:
    """在读取成员前限制压缩包规模，避免小文件触发超大内存分配。"""
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError("压缩包文件数量超过限制")
    total_size = 0
    for info in members:
        if info.is_dir():
            continue
        size = max(int(info.file_size), 0)
        compressed = max(int(info.compress_size), 1)
        if size > MAX_ARCHIVE_MEMBER_BYTES:
            raise ValueError(f"压缩包成员解压后超过大小限制: {info.filename}")
        total_size += size
        if total_size > MAX_ARCHIVE_TOTAL_BYTES:
            raise ValueError("压缩包解压后总大小超过限制")
        if size >= 1024 * 1024 and size / compressed > MAX_ARCHIVE_COMPRESSION_RATIO:
            raise ValueError(f"压缩包成员压缩比异常: {info.filename}")


def _plain_text(root: ET.Element) -> str:
    return " ".join("".join(root.itertext()).split())


def _split_chapters(text: str, fallback_title: str) -> tuple[str, list[dict[str, Any]]]:
    title = fallback_title
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in lines:
        if line.strip().startswith("# "):
            title = line.strip()[2:].strip() or title
            break
    starts: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = CHAPTER_RE.match(line)
        if match:
            starts.append((index, int(match.group(1)), match.group(2).strip()))
    if not starts:
        content = text.strip()
        fallback = [{"chapter_number": 1, "title": "", "content": content, "summary": content[:500]}]
        return title, fallback if content else []
    chapters: list[dict[str, Any]] = []
    for position, (line_index, number, chapter_title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        content_lines = lines[line_index + 1 : end]
        content = "\n".join(content_lines).strip()
        chapters.append({
            "chapter_number": number,
            "title": chapter_title,
            "content": content,
            "summary": content[:500],
        })
    return title, chapters


def _parse_docx(data: bytes, fallback_title: str) -> tuple[str, list[dict[str, Any]]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _validate_archive_limits(archive)
        root = ET.fromstring(archive.read("word/document.xml"))
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        paragraphs.append(text)
    return _split_chapters("\n".join(paragraphs), fallback_title)


def _epub_opf_path(archive: zipfile.ZipFile) -> str:
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    rootfile = next(iter(container.findall(".//{*}rootfile")), None)
    if rootfile is None:
        raise ValueError("EPUB 缺少 OPF 根文件")
    return str(rootfile.attrib.get("full-path", ""))


def _parse_epub(data: bytes, fallback_title: str) -> tuple[str, list[dict[str, Any]]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _validate_archive_limits(archive)
        opf_path = _epub_opf_path(archive)
        opf = ET.fromstring(archive.read(opf_path))
        base = posixpath.dirname(opf_path)
        manifest = {
            item.attrib.get("id", ""): item.attrib
            for item in opf.findall(".//{*}manifest/{*}item")
        }
        chapters: list[dict[str, Any]] = []
        title_node = opf.find(".//{*}title")
        title = (title_node.text or "").strip() if title_node is not None else fallback_title
        for index, itemref in enumerate(opf.findall(".//{*}spine/{*}itemref"), start=1):
            item = manifest.get(itemref.attrib.get("idref", ""))
            if not item or not item.get("href"):
                continue
            resource = posixpath.normpath(posixpath.join(base, item["href"]))
            root = ET.fromstring(archive.read(resource))
            text = "\n".join(_plain_text(node) for node in root.findall(".//{*}body/*"))
            heading_node = next(iter(root.findall(".//{*}h1")), None)
            heading = _plain_text(heading_node) if heading_node is not None else f"第{index}章"
            match = CHAPTER_RE.match(heading)
            number = int(match.group(1)) if match else index
            chapter_title = match.group(2).strip() if match else heading
            cleaned = text.strip()
            chapters.append({
                "chapter_number": number,
                "title": chapter_title,
                "content": cleaned,
                "summary": cleaned[:500],
            })
    return title or fallback_title, chapters


def _parse_backup(data: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _validate_archive_limits(archive)
        _validate_backup_members(archive)
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema_version") not in {"novel-agent-backup-v1", "novel-agent-backup-v2"}:
            raise ValueError("不支持的备份版本")
        checksums = manifest.get("checksums") or {}
        if checksums:
            if not isinstance(checksums, dict):
                raise ValueError("备份 checksum 清单无效")
            for name, expected in checksums.items():
                if name not in archive.namelist():
                    raise ValueError(f"备份文件缺失:{name}")
                actual = hashlib.sha256(archive.read(name)).hexdigest()
                if actual != str(expected):
                    raise ValueError(f"备份文件校验失败:{name}")
        novel = json.loads(archive.read("novel.json"))
        progress = json.loads(archive.read("progress.json")) if "progress.json" in archive.namelist() else {}
        snapshots = (
            json.loads(archive.read("memory_snapshots.json"))
            if "memory_snapshots.json" in archive.namelist()
            else []
        )
        quality_runs = (
            json.loads(archive.read("memory_quality_runs.json"))
            if "memory_quality_runs.json" in archive.namelist()
            else []
        )
        checkpoint = (
            json.loads(archive.read("checkpoint.json"))
            if "checkpoint.json" in archive.namelist()
            else {}
        )
        chapters = []
        chapter_names = sorted(
            item for item in archive.namelist()
            if item.startswith("chapters/") and item.endswith(".json")
        )
        for name in chapter_names:
            chapters.append(json.loads(archive.read(name)))
    return {
        "novel": novel,
        "chapters": chapters,
        "progress": progress,
        "memory_snapshots": snapshots,
        "memory_quality_runs": quality_runs,
        "checkpoint": checkpoint,
    }


def _validate_backup_members(archive: zipfile.ZipFile) -> None:
    """拒绝绝对路径、父目录跳转和未知目录，避免导入路径穿越。"""
    for name in archive.namelist():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("备份包含非法路径")
        if name == "manifest.json" or name in {
            "novel.json", "progress.json", "memory_snapshots.json",
            "memory_quality_runs.json", "checkpoint.json",
        }:
            continue
        if not (name.startswith("chapters/") and name.endswith(".json")):
            raise ValueError(f"备份包含未知文件:{name}")


def parse_import_bytes(
    data: bytes,
    filename: str,
    format: str = "",
    password: str = "",
) -> dict[str, Any]:
    """按扩展名解析导入内容，返回统一的作品与章节载荷。"""
    if is_encrypted_backup(data):
        data = decrypt_backup(data, password)
        format = "backup"
    name = str(filename or "导入").lower()
    normalized = str(format or "").casefold().lstrip(".")
    if normalized in {"zip", "backup", "novel-backup"} or name.endswith(".novel-backup.zip"):
        return _parse_backup(data)
    if not normalized:
        normalized = name.rsplit(".", 1)[-1] if "." in name else "txt"
    fallback = PurePosixPath(filename or "导入").stem or "导入作品"
    if normalized == "docx":
        title, chapters = _parse_docx(data, fallback)
    elif normalized == "epub":
        title, chapters = _parse_epub(data, fallback)
    else:
        text = data.decode("utf-8-sig", errors="replace")
        title, chapters = _split_chapters(text, fallback)
    return {
        "novel": {
            "title": title,
            "genre": "",
            "inspiration": "导入作品",
            "style": "",
            "total_chapters": max(len(chapters), 1),
        },
        "chapters": chapters,
        "progress": {},
        "memory_snapshots": [],
        "memory_quality_runs": [],
        "checkpoint": {},
    }
