# Cookie Authentication And E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move browser sessions out of Web Storage, protect cookie-authenticated mutations with CSRF, and verify critical workflows in a real browser.

**Architecture:** FastAPI sets an HttpOnly session cookie plus a readable CSRF cookie. Middleware accepts Cookie first and Bearer second, enforces CSRF only for cookie-authenticated mutations, and preserves CLI compatibility. React uses credentialed fetch and reads only the CSRF cookie.

**Tech Stack:** FastAPI, SQLite sessions, React/TypeScript, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-20-production-hardening-design.md`

## Global Constraints

- Production session Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.
- Bearer authentication remains supported for CLI and existing API clients.
- Cookie mutations require `X-CSRF-Token`; Bearer mutations do not.
- Browser E2E must use isolated runtime paths and no external model network.

---

### Task 1: Backend Cookie Session And CSRF

**Files:**
- Modify: `src/novel_agent/config.py`
- Modify: `src/novel_agent/security.py`
- Modify: `src/novel_agent/api/server.py`
- Modify: `tests/test_security.py`
- Modify: `tests/test_api.py`
- Modify: `.env.example`
- Modify: `.env.production.example`

**Interfaces:**
- Produces: `SESSION_COOKIE_NAME = 'novel_agent_session'`, `CSRF_COOKIE_NAME = 'novel_agent_csrf'`.
- Produces: `new_csrf_token() -> str` and `verify_csrf_token(expected: str, actual: str) -> bool`.
- Consumes: existing hashed server-side session storage.

- [x] **Step 1: Write failing security and API tests**

Test token generation and constant-time equality. Test login sets both cookies; production session cookie contains `Secure`, `HttpOnly` and `SameSite=lax`; Cookie-authenticated POST without CSRF returns 403; matching header/cookie succeeds; Bearer POST remains valid; logout revokes and clears both cookies.

- [x] **Step 2: Verify RED**

Run: `$env:TEMP='D:\novel-agent\.tmp\pytest-temp'; $env:TMP=$env:TEMP; .\.venv\Scripts\python.exe -m pytest tests/test_security.py tests/test_api.py -k "cookie or csrf or bearer" -q`

Expected: FAIL because no cookies or CSRF enforcement exist.

- [x] **Step 3: Add explicit cookie configuration**

Add `auth_cookie_secure: bool | None = None` and derive secure mode from `APP_ENVIRONMENT=production` when unset. Add cookie names and CSRF helpers to `security.py`.

- [x] **Step 4: Implement dual authentication and CSRF middleware**

Resolve the session token from Cookie first, then Bearer. Store the chosen transport on `request.state.auth_transport`. For authenticated Cookie requests using `POST`, `PUT`, `PATCH`, or `DELETE`, compare `X-CSRF-Token` with the CSRF cookie before role/rate-limit logic; exempt `/api/auth/login` and `/api/auth/register`.

- [x] **Step 5: Set and clear cookies**

Return `JSONResponse` from login/register, set the session and CSRF cookies, and include `csrf_token` in the compatibility response. Logout revokes the chosen session and deletes both cookies with matching attributes.

- [x] **Step 6: Configure credentialed CORS**

Set `allow_credentials=True` and allow `X-CSRF-Token` plus `X-Backup-Password`. Keep explicit origins and the production wildcard rejection.

- [x] **Step 7: Verify focused tests**

Run the command from Step 2. Expected: all selected tests pass.

- [x] **Step 8: Commit**

```powershell
git add src/novel_agent/config.py src/novel_agent/security.py src/novel_agent/api/server.py tests/test_security.py tests/test_api.py .env.example .env.production.example
git commit -m "feat: add secure cookie sessions and CSRF"
```

### Task 2: React Cookie Client

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: session and CSRF cookies from Task 1.
- Produces: all API fetches use `credentials: 'include'`; mutation requests send `X-CSRF-Token` from the CSRF cookie.

- [x] **Step 1: Replace the old passing token test with failing cookie tests**

Assert login does not write `novel_agent_access_token`; subsequent requests contain `credentials: 'include'`, no Authorization header, and mutations include `X-CSRF-Token` when the CSRF cookie is present.

- [x] **Step 2: Verify RED**

Run: `npm test -- src/api.test.ts` in `frontend`.

Expected: FAIL because the client still stores and sends the Bearer token.

- [x] **Step 3: Implement the cookie client**

Remove access-token storage and `storedAuthToken()`. Add `credentials: 'include'` to API, streaming, export and download requests. Parse only `novel_agent_csrf` from `document.cookie`; add `X-CSRF-Token` to mutating requests. Keep stale token removal during startup.

- [x] **Step 4: Remove reload-dependent login handling**

After login/register, update `authUser` from the response and close the dialog. After logout, clear `authUser`; do not rely on a full page reload to establish cookie state.

- [x] **Step 5: Verify frontend checks**

Run:

```powershell
npm test -- src/api.test.ts src/components/AuthDialog.test.tsx
npm run typecheck
npm run build
```

Expected: all commands pass.

- [x] **Step 6: Commit**

```powershell
git add frontend/src/types.ts frontend/src/api.ts frontend/src/api.test.ts frontend/src/App.tsx
git commit -m "feat(frontend): use cookie-backed sessions"
```

### Task 3: Deterministic Browser E2E

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/auth-and-backup.spec.ts`
- Create: `scripts/e2e_server.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `npm run test:e2e` using isolated FastAPI and Vite web servers.
- Consumes: Cookie/CSRF behavior from Tasks 1-2.

- [x] **Step 1: Install and configure Playwright**

Run `npm install --save-dev --save-exact @playwright/test@1.55.1`, then add scripts `test:e2e` and `test:e2e:install`. Version 1.55.1 is the minimum patch for GHSA-7mvr-c777-76hp. Configure desktop Chromium and a mobile Chromium project, screenshots/traces only on failure, and web servers bound to dedicated test ports.

- [x] **Step 2: Create an isolated E2E server**

`scripts/e2e_server.py` must set SQLite, checkpoint, Chroma, transfer and key paths under a supplied temporary root before importing `novel_agent.api.server`, then launch uvicorn. Configure auth on and an environment model fallback without making provider calls.

- [x] **Step 3: Write the first browser test and verify failure**

Test registration, cookie-based refresh recovery, novel creation, encrypted backup download, logout and rejected post-logout access. Assert console errors are empty.

Run: `npm run test:e2e -- --project=chromium`.

Expected before server/client wiring is complete: FAIL at the first missing cookie or CSRF behavior.

- [x] **Step 4: Complete deterministic fixtures**

Use API setup for data that does not need UI coverage. Do not start a real generation job in the initial E2E because provider calls are out of scope; exercise persisted job/review recovery through existing deterministic API test coverage.

- [x] **Step 5: Add CI browser job**

Install Chromium with Playwright dependencies, run `npm run test:e2e`, and upload the Playwright report only on failure.

- [x] **Step 6: Verify E2E**

Run: `npm run test:e2e`.

Expected: desktop and mobile Chromium projects pass without console errors.

- [x] **Step 7: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/playwright.config.ts frontend/e2e/auth-and-backup.spec.ts scripts/e2e_server.py .github/workflows/ci.yml .gitignore
git commit -m "test: add browser authentication smoke flow"
```

### Task 4: Optional Real-Model Compatibility Workflow

**Files:**
- Create: `.github/workflows/real-model-e2e.yml`
- Create: `scripts/real_model_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Produces: manual/nightly workflow report with provider, model, state transitions and redacted failure category.

- [x] **Step 1: Add script contract tests**

Add a no-key invocation test to `tests/test_model_resolver.py` that expects exit code 2 and a stable `skipped` JSON result without revealing environment values.

- [x] **Step 2: Verify RED**

Run: `$env:TEMP='D:\novel-agent\.tmp\pytest-temp'; $env:TMP=$env:TEMP; .\.venv\Scripts\python.exe -m pytest tests/test_model_resolver.py -k real_model_smoke -q`

Expected: FAIL because the script does not exist.

- [x] **Step 3: Implement the bounded smoke script**

Validate one configured chat model, one embedding model and one single-chapter auto-approved workflow with a strict token budget. Emit JSON containing no prompt, generated prose or key material. Exit 0 on pass, 1 on failure, 2 when credentials are absent.

- [x] **Step 4: Add manual/nightly workflow**

Run on `workflow_dispatch` and weekly schedule. Skip cleanly when repository secrets are absent; upload the JSON report as an artifact. Do not add this workflow to pull-request required checks.

- [x] **Step 5: Document and verify**

Document required secret names and cost bounds. Run the no-key test and Ruff against the script.

- [x] **Step 6: Commit**

```powershell
git add .github/workflows/real-model-e2e.yml scripts/real_model_smoke.py tests/test_model_resolver.py README.md
git commit -m "test: add optional real-model compatibility smoke"
```

### Task 5: Full Verification

**Files:**
- Verify only.

- [x] **Step 1: Backend quality gates**

```powershell
$env:TEMP='D:\novel-agent\.tmp\pytest-temp'
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts main.py
.\.venv\Scripts\python.exe -m scripts.run_evaluations
.\.venv\Scripts\python.exe -m scripts.check_deployment
```

- [x] **Step 2: Frontend quality gates**

```powershell
npm test
npm run typecheck
npm run build
npm run test:e2e
```

- [x] **Step 3: Review change scope**

Run `git diff --check`, `git status --short`, and `git log --oneline main..HEAD`. Confirm runtime databases, secrets, generated reports and browser artifacts are untracked or ignored.
