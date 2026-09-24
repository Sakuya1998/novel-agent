# React Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace the Streamlit workbench with an independently buildable React + TypeScript application while keeping FastAPI/LangGraph as the backend authority.

**Architecture:** Add a Vite React client under `frontend/`, use typed fetch helpers for REST and NDJSON streams, and add a read-only backend state summary endpoint. Keep Streamlit available during migration.

**Tech Stack:** React 19, TypeScript, Vite, CSS modules via a single app stylesheet, FastAPI CORS, browser `fetch` streaming.

---

### Task 1: Backend frontend boundary

**Files:**
- Modify: `config.py`
- Modify: `api/server.py`
- Test: `tests/test_api.py`

- [x] Add `frontend_origins` configuration parsed from `FRONTEND_ORIGINS`, defaulting to localhost Vite ports.
- [x] Add `CORSMiddleware` to the FastAPI app with explicit origins, credentials disabled, and GET/POST methods.
- [x] Add `GET /api/novels/{novel_id}/state`; derive `human_review`, `completed`, `running`, `idle`, and legacy read-only states from the LangGraph snapshot plus SQLite chapters.
- [x] Add tests for the state endpoint on a missing novel, an empty novel, and a human-review checkpoint.
- [x] Run `uv run --isolated --with ".[dev]" pytest -q tests/test_api.py`.

### Task 2: Vite React application shell

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`

- [x] Define Vite scripts for `dev`, `build`, `typecheck`, and `preview`.
- [x] Build the three-column editorial workbench shell with responsive collapse.
- [x] Add semantic loading, empty, error, and selected-work states.
- [x] Run `npm.cmd install` and `npm.cmd run build`.

### Task 3: Typed API and stream state

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/useWorkbench.ts`

- [x] Define Novel, Chapter, WorkbenchState, and NDJSON event unions.
- [x] Implement REST helpers for list/create/detail/state and POST stream readers for run/resume.
- [x] Parse the response body incrementally by newline and update stage, review, error, and completion state.
- [x] Ensure refresh rehydrates the selected novel from REST state without duplicating requests.

### Task 4: Workbench interactions

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/NovelSidebar.tsx`
- Create: `frontend/src/components/StageRail.tsx`
- Create: `frontend/src/components/ReviewPanel.tsx`
- Create: `frontend/src/components/ChapterReader.tsx`

- [x] Wire new-novel form to POST `/api/novels` then `/run`.
- [x] Wire continue to `/run`, approval/feedback to `/resume`, and disable controls while streaming.
- [x] Render persistence errors and structured consistency issues from interrupt events.
- [x] Render completed chapters from SQLite-backed detail responses.
- [x] Keep component props typed and avoid inline component definitions or unnecessary effects.

### Task 5: Runtime verification and docs

**Files:**
- Modify: `README.md`
- Create: `frontend/.env.example`
- Create: `frontend/src/App.test.tsx` (if test runner is added)

- [x] Document separate FastAPI and Vite startup commands and proxy/CORS behavior.
- [x] Start FastAPI and Vite locally, verify page identity and meaningful DOM.
- [x] Exercise create → stream progress → human review → approve/feedback → completion.
- [x] Verify mobile-width layout and browser console health.
- [x] Run backend pytest/ruff plus frontend typecheck/build.
