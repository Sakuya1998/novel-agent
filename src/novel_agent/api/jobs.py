"""Stable job and event representations for the versioned API."""

from typing import Any

JOB_STATUSES = {
    "queued", "running", "waiting_review", "completed", "failed", "cancelled", "interrupted",
}
TERMINAL_JOB_STATUSES = {"waiting_review", "completed", "failed", "cancelled", "interrupted"}


def job_event_envelope(event: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Map the persisted event row to its public, resumable envelope."""
    payload = event.get("payload")
    event_type = str(event.get("event_type") or (payload or {}).get("type") or "event")
    return {
        "job_id": str(job_id),
        "sequence": int(event.get("sequence", 0) or 0),
        "type": event_type,
        "payload": payload if isinstance(payload, dict) else {},
        "created_at": str(event.get("created_at", "")),
    }
