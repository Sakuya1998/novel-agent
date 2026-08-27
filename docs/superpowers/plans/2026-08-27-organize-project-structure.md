# Project Structure Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move application Python code into a standard `src/novel_agent` package, isolate project assets by responsibility, and remove obsolete build/interface residue without changing runtime behavior.

**Architecture:** The repository will use a `src` layout for importable application code. Root-level files remain limited to project metadata, deployment entrypoints, documentation, tests, scripts, and runtime data directories. A small root `main.py` compatibility launcher will preserve the documented CLI command while the API and Docker runtime use the packaged module.

**Tech Stack:** Python 3.14, setuptools, FastAPI, LangGraph, SQLite/ChromaDB, React/Vite, Docker Compose, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-17-react-workbench-design.md` and the approved directory-organization design in the preceding task discussion.

## Global Constraints

- Preserve existing API paths, CLI behavior, frontend behavior, database locations, and environment variable names.
- Keep runtime data in root `data/`, `memory/`, and `output/`; do not delete valid databases or key files.
- Remove obsolete Streamlit/build artifacts only after confirming they are not tracked application sources.
- Update every source, test, deployment, and documentation reference affected by the package move.

---

### Task 1: Establish The Python Source Layout

**Files:**
- Create: `src/novel_agent/__init__.py`
- Move: root Python application packages into `src/novel_agent/`
- Modify: `src/novel_agent/config.py`

- [x] Move `agents`, `api`, `graph`, `memory`, `models`, `prompts`, and `tools` into `src/novel_agent/` and move `config.py`, `security.py`, and `main.py` there as package modules.
- [x] Add package metadata and make project-root path resolution explicit for runtime directories and prompt files.
- [x] Confirm the moved tree contains no `ui` source and no build output.

### Task 2: Normalize Imports And Entry Points

**Files:**
- Modify: all Python files under `src/novel_agent/`
- Modify: `tests/`, `scripts/`, `Dockerfile`, `pyproject.toml`, `.github/workflows/ci.yml`
- Create: root `main.py`

- [x] Replace top-level imports with `novel_agent.*` imports and preserve package-local behavior.
- [x] Configure setuptools package discovery from `src` and keep `python main.py` as a compatibility launcher.
- [x] Switch service commands and maintenance scripts to packaged module paths where required.

### Task 3: Document The New Boundaries

**Files:**
- Modify: `README.md`, `.dockerignore`, `.gitignore`
- Create: `src/README.md` or equivalent package guidance only if needed

- [x] Update project structure, startup commands, Docker copy paths, and development commands.
- [x] Explain that `data/`, `memory/`, and `output/` are runtime directories and `src/` is application code.

### Task 4: Remove Obsolete Local Artifacts

**Files:**
- Delete: tracked obsolete files only if any remain after migration
- Remove: `build/`, stale `ui/` cache residue, `novel_agent.egg-info/`, Python caches

- [x] Verify `ui/` has no tracked source files and remove only stale generated residue.
- [x] Remove old build metadata and caches without touching runtime databases, keys, backups, or transfer files.

### Task 5: Verify The Refactor

- [x] Run Python compile/import checks and the full backend test suite with development dependencies.
- [x] Run Ruff, frontend tests/typecheck/build, and Docker/Compose configuration checks.
- [x] Inspect `git diff` and `git status` for unintended data or generated-file changes.
