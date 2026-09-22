"""Small, opaque cursor pagination helpers for public API collections."""

import base64
import json
from typing import Any


def encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": max(offset, 0)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload: Any = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        offset = int(payload["offset"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise ValueError("游标无效") from exc
    if offset < 0:
        raise ValueError("游标无效")
    return offset


def paginate(items: list[dict], *, limit: int, cursor: str | None) -> dict[str, Any]:
    offset = decode_cursor(cursor)
    page = items[offset : offset + limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(items)
    return {
        "items": page,
        "limit": limit,
        "cursor": cursor,
        "next_cursor": encode_cursor(next_offset) if has_more else None,
        "has_more": has_more,
    }
