# Job Events API v1

Run jobs are created with `POST /api/v1/novels/{novel_id}/jobs/{run|resume|candidates|canon|book-revision}`.
Creation endpoints accept `Idempotency-Key`; replaying the same key and request returns the original job.
Reusing that key for a different request returns `409`.

Read current job status with `GET /api/v1/jobs/{job_id}`. Poll events with
`GET /api/v1/jobs/{job_id}/events?after_sequence=0&limit=200`. Every public event has this shape:

```json
{
  "job_id": "job_123",
  "sequence": 1,
  "type": "job_started",
  "payload": {"attempt": 1},
  "created_at": "2026-09-23T07:00:00"
}
```

The response includes `next_after_sequence`, which is the greatest sequence returned (or the supplied
cursor when no events were returned). Persist it client-side and supply it on reconnect; event sequence
numbers are increasing per job, and a client should ignore any duplicate sequence it has already applied.
The legacy `/api/*` event route remains unchanged during migration.

Job statuses are `queued`, `running`, `waiting_review`, `completed`, `failed`, `cancelled`, and
`interrupted`. `waiting_review` means generation paused for user input and is resumable by creating a
new resume job. `interrupted` means the worker stopped without completing; inspect the novel checkpoint
before starting a new run. `completed`, `failed`, `cancelled`, and `interrupted` are terminal.

Cancellation is requested with `POST /api/v1/jobs/{job_id}/cancel`, optionally with an
`Idempotency-Key`. Job reads, events, cancellation, and creation are scoped to the novel's workspace;
out-of-workspace jobs return `404`. Viewer roles are read-only. Error event messages are sanitized and
must not contain provider secrets or full prompts.
