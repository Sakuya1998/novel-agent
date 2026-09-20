# Locked Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local CI and production images install the exact Python dependency graph in `uv.lock`.

**Architecture:** `pyproject.toml` remains the direct dependency declaration and `uv.lock` becomes the deployed resolution. CI creates `.venv` through uv; Docker copies an already locked production environment from a builder stage.

**Tech Stack:** uv, Python 3.14, GitHub Actions, Docker BuildKit, pip-audit.

**Spec:** `docs/superpowers/specs/2026-09-20-production-hardening-design.md`

## Global Constraints

- Locked installs use `--locked`; no CI step may silently update `uv.lock`.
- Runtime image remains non-root and does not contain development dependencies or uv caches.
- Frontend remains on `npm ci` and `package-lock.json`.

---

### Task 1: CI Uses The Lockfile

**Files:**
- Modify: `.gitignore`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Create: `uv.lock`

**Interfaces:**
- Produces: CI commands executed through `uv run --locked` in the project `.venv`.

- [x] **Step 1: Record the failing policy check**

Run: `rg -n "pip install -r requirements.txt" .github/workflows/ci.yml Dockerfile`

Expected: matches in both CI and Docker, proving release paths bypass the lockfile.

- [x] **Step 2: Switch the lint/test job**

Use `astral-sh/setup-uv@v6` with `version: "0.12.1"`, run `uv sync --locked --all-extras`, then execute Ruff, pytest and evaluations with `uv run --locked`.
Track the generated `uv.lock`; locked CI cannot work while the file is ignored.

- [x] **Step 3: Switch dependency audit input**

Export the locked production dependency set with `uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file .tmp/locked-requirements.txt`, then run pip-audit against that file with the existing scoped Chroma exceptions.

- [x] **Step 4: Update local documentation**

Replace the primary `pip install -e ".[dev]"` path with `uv sync --locked --all-extras`; retain pip as a clearly labeled compatibility path that is not release-reproducible.

- [x] **Step 5: Validate workflow syntax and policy**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8'))"
rg -n "uv sync --locked|uv run --locked|uv export --locked" .github/workflows/ci.yml README.md
```

Expected: YAML parses and all three locked commands are present.

- [x] **Step 6: Commit**

```powershell
git add .github/workflows/ci.yml README.md
git commit -m "ci: install Python dependencies from uv lock"
```

### Task 2: Docker Uses The Lockfile

**Files:**
- Modify: `Dockerfile`
- Modify: `scripts/check_deployment.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: a builder-created `/opt/venv` installed via `uv sync --locked --no-dev`.

- [x] **Step 1: Write the failing deployment policy test**

Add a test that reads `Dockerfile` and asserts it copies `uv.lock`, contains `uv sync --locked --no-dev`, and does not contain `pip install --no-cache-dir -r requirements.txt`.

- [x] **Step 2: Verify RED**

Run: `$env:TEMP='D:\novel-agent\.tmp\pytest-temp'; $env:TMP=$env:TEMP; .\.venv\Scripts\python.exe -m pytest tests/test_config.py -k docker -q`

Expected: FAIL because Docker still installs from `requirements.txt`.

- [x] **Step 3: Implement locked Docker build**

Copy `/uv` from `ghcr.io/astral-sh/uv:0.12.1` into the builder, set `UV_PROJECT_ENVIRONMENT=/opt/venv`, copy `pyproject.toml`, `uv.lock`, README and `src`, then run `uv sync --locked --no-dev --no-editable`. Keep the current runtime stage and `/opt/venv` copy.

- [x] **Step 4: Strengthen offline deployment checks**

Require `COPY ... uv.lock`, `uv sync --locked --no-dev`, non-root runtime and the existing security markers in `scripts/check_deployment.py`.

- [x] **Step 5: Verify**

Run:

```powershell
$env:TEMP='D:\novel-agent\.tmp\pytest-temp'
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
$env:APP_ENVIRONMENT='production'
$env:AUTH_ENABLED='true'
$env:FRONTEND_ORIGINS='http://localhost:5173'
.\.venv\Scripts\python.exe -m scripts.check_deployment
```

Expected: tests pass and deployment checks print `deployment checks passed`.

- [x] **Step 6: Commit**

```powershell
git add Dockerfile scripts/check_deployment.py tests/test_config.py
git commit -m "build: create image from locked Python dependencies"
```
