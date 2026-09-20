# Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix encrypted-backup CORS preflight and make readiness report the actual database/environment model configuration.

**Architecture:** Keep FastAPI middleware and the existing model settings store as the authority. Add one read-only readiness helper that validates routes without contacting providers, then expose its result through `/readyz`.

**Tech Stack:** Python 3.14, FastAPI/Starlette CORS, SQLite, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-09-20-production-hardening-design.md`

## Global Constraints

- Do not change LangGraph topology or model prompts.
- CORS origins remain explicit; production must continue rejecting `*`.
- Readiness must not call an external model provider.
- Every behavior change starts with a failing test.

---

### Task 1: Encrypted Backup CORS Preflight

**Files:**
- Modify: `tests/test_api.py`
- Modify: `src/novel_agent/api/server.py:176-183`

**Interfaces:**
- Consumes: Starlette `CORSMiddleware` preflight handling.
- Produces: `X-Backup-Password` in the allowed CORS request-header set.

- [ ] **Step 1: Write the failing preflight test**

Extend `test_frontend_cors_allows_vite_origin` with a second OPTIONS request carrying `Access-Control-Request-Headers: x-backup-password`, and assert status 200 plus `x-backup-password` in `access-control-allow-headers`.

- [ ] **Step 2: Verify RED**

Run: `$env:TEMP='D:\novel-agent\.tmp\pytest-temp'; $env:TMP=$env:TEMP; .\.venv\Scripts\python.exe -m pytest tests/test_api.py::test_frontend_cors_allows_vite_origin -q`

Expected: FAIL because the encrypted-backup preflight returns 400.

- [ ] **Step 3: Implement the minimal CORS change**

Set `allow_headers` to `['Content-Type', 'Authorization', 'X-Backup-Password']` without changing origins, methods, or credentials.

- [ ] **Step 4: Verify GREEN**

Run the focused command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_api.py src/novel_agent/api/server.py
git commit -m "fix: allow encrypted backup CORS header"
```

### Task 2: Accurate Model Readiness

**Files:**
- Modify: `tests/test_api.py`
- Modify: `src/novel_agent/models/resolver.py`
- Modify: `src/novel_agent/api/server.py:3204-3235`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: `ModelResolver.configuration_status() -> dict[str, str]` with `status` and `source`.
- Consumes: `ModelSettingsStore.get_routes()`, `ModelResolver.validate_runtime()` and environment fallback settings.

- [ ] **Step 1: Write failing readiness tests**

Add API tests for three states: complete database routes return `configured/database`; complete environment fallback returns `configured/environment`; missing configuration returns HTTP 503 with `unconfigured/none`. Patch `app.state.model_settings_store` only through the existing `api_env` fixture.

- [ ] **Step 2: Verify RED**

Run: `$env:TEMP='D:\novel-agent\.tmp\pytest-temp'; $env:TMP=$env:TEMP; .\.venv\Scripts\python.exe -m pytest tests/test_api.py -k readiness -q`

Expected: FAIL because `/readyz` only checks environment keys and reports `fallback`.

- [ ] **Step 3: Implement readiness status**

Add `configuration_status()` to `ModelResolver`. It must call `validate_runtime()` without provider requests, return database when routes exist and validate, environment when routes are empty and fallback validates, and `unconfigured/none` with a sanitized detail on `ModelConfigurationError`.

Update `/readyz` to place that object in `checks['model']` and treat only `ok` or `configured` as healthy.

- [ ] **Step 4: Keep Compose smoke configuration explicit**

In the Compose smoke step, set `OPENAI_API_KEY=test-readiness-key` so `.env.production.example` can remain secret-free while readiness has a syntactically complete environment fallback.

Document that `/readyz` returns 503 until model routes or environment fallback are configured.

- [ ] **Step 5: Verify focused and full checks**

Run:

```powershell
$env:TEMP='D:\novel-agent\.tmp\pytest-temp'
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_model_resolver.py -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts main.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 6: Commit**

```powershell
git add tests/test_api.py src/novel_agent/models/resolver.py src/novel_agent/api/server.py .github/workflows/ci.yml README.md
git commit -m "fix: report effective model readiness"
```

