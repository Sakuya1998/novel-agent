"""Versioned public API surface."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.get("", include_in_schema=True)
async def api_metadata() -> dict[str, str]:
    return {"version": "v1", "service": "novel-agent"}
