# Remove Streamlit Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the migration-only Streamlit interface and dependency while preserving React, FastAPI, CLI, and persistent data behavior.

**Architecture:** Delete the isolated `ui` package and its dedicated test, then remove every build, packaging, documentation, and dependency reference to it. No runtime data schemas or shared graph components change.

**Tech Stack:** Python 3.14, FastAPI, LangGraph, React, Ruff, pytest, Vitest

---

### Task 1: Delete The Streamlit-Only Runtime

**Files:**
- Delete: `ui/__init__.py`
- Delete: `ui/runtime.py`
- Delete: `ui/streamlit_app.py`
- Delete: `tests/test_ui_runtime.py`

- [ ] **Step 1: Delete the Streamlit package and dedicated test**

Use `apply_patch` to delete the four files listed above.

- [ ] **Step 2: Confirm no Python import remains**

Run:

```powershell
rg -n "streamlit|StreamlitGraphRuntime|ui\.runtime" agents api graph main.py memory models tests tools
```

Expected: no matches.

### Task 2: Remove Packaging And Deployment References

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `scripts/check_versions.py`
- Modify: `Dockerfile`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Remove the dependency and package declarations**

Delete `streamlit>=1.60`, remove `ui` from package discovery and Ruff first-party modules, and remove `streamlit` from the version check list.

- [ ] **Step 2: Remove deployment and CI paths**

Delete `COPY ui ./ui` from the Dockerfile and remove `ui` from the CI Ruff command.

- [ ] **Step 3: Confirm packaging references are gone**

Run:

```powershell
rg -n "streamlit|\bui\b" pyproject.toml requirements.txt scripts/check_versions.py Dockerfile .github/workflows/ci.yml
```

Expected: no matches referring to the deleted interface.

### Task 3: Update Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Remove Streamlit startup and tree documentation**

Delete the Streamlit launch command and migration-interface tree entry, and remove `ui` from the documented Ruff command.

- [ ] **Step 2: Confirm public documentation names React as the web interface**

Run:

```powershell
rg -n "streamlit|ui/streamlit|ruff check .* ui " README.md
```

Expected: no matches.

### Task 4: Verify The Reduced Application

**Files:**
- Verify only

- [ ] **Step 1: Run backend tests and lint**

```powershell
uv run --isolated --with ".[dev]" pytest -q
uvx ruff check agents graph memory tools prompts models api config.py main.py tests
```

Expected: all tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 2: Run frontend verification**

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
```

Expected: Vitest, TypeScript, and the Vite production build pass.

- [ ] **Step 3: Check repository cleanliness**

```powershell
git diff --check
rg -n "streamlit|StreamlitGraphRuntime|ui/streamlit|test_ui_runtime" . --glob '!docs/superpowers/**'
```

Expected: no diff errors and no active-code references to Streamlit.
