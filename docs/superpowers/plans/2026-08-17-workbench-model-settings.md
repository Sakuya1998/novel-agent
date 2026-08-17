# Workbench Model Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add encrypted model-provider management to the React workbench and route creative, analysis, and embedding calls through independently selectable models.

**Architecture:** Persist provider profiles and three global routes in the existing application SQLite database while encrypting API keys with a local Fernet master key. Resolve the latest route before constructing each LangChain client, expose a redacted FastAPI settings API, and manage profiles and routes in a dedicated React dialog.

**Tech Stack:** Python 3.14, FastAPI, SQLite, cryptography/Fernet, LangChain OpenAI/Anthropic, React 19, TypeScript, Vitest, Testing Library

---

## File Structure

- Create `models/model_settings.py`: provider templates, encrypted profile persistence, route transactions, and public redaction.
- Create `models/resolver.py`: environment fallback, purpose-based resolution, LangChain client factories, and connection tests.
- Create `api/model_settings.py`: Pydantic request models and FastAPI router for model settings.
- Create `frontend/src/useModelSettings.ts`: settings loading and mutation state.
- Create `frontend/src/components/ModelSettingsDialog.tsx`: accessible settings dialog and tabs.
- Create `frontend/src/components/ModelProfilesPanel.tsx`: provider profile list and editor.
- Create `frontend/src/components/ModelRoutesPanel.tsx`: creative, analysis, and embedding selectors.
- Create `tests/test_model_settings.py`: encrypted persistence and route behavior.
- Create `tests/test_model_resolver.py`: provider mapping, fallback, and cache invalidation.
- Create `frontend/src/components/ModelSettingsDialog.test.tsx`: workbench settings interaction tests.
- Modify `config.py`: master-key path.
- Modify `models/llm.py`: delegate chat model construction to the resolver while preserving existing call sites.
- Modify `memory/vector_store.py`: obtain embeddings from the resolver.
- Modify `api/server.py`: initialize settings storage, mount router, track active streams, and validate routes before execution.
- Modify `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/App.tsx`, and `frontend/src/styles.css`: public types, API calls, entry point, and responsive styling.
- Modify `pyproject.toml`, `frontend/package.json`, `.env.example`, `.gitignore`, `.github/workflows/ci.yml`, `README.md`, and Docker configuration: dependencies, runtime paths, tests, and documentation.

## Task 1: Configuration And Encryption Dependency

**Files:**
- Modify: `config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing configuration test**

Add a test that proves the master-key parent directory is created:

```python
def test_config_creates_model_secret_key_parent(tmp_path):
    key_path = tmp_path / "secrets" / "model-settings.key"
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(key_path),
    )
    cfg.ensure_dirs()
    assert key_path.parent.is_dir()
```

- [ ] **Step 2: Verify the test fails for the missing field**

Run:

```powershell
uv run --isolated --with ".[dev]" pytest tests/test_config.py::test_config_creates_model_secret_key_parent -vv
```

Expected: FAIL because `Config` ignores `model_secret_key_path` and does not create its parent.

- [ ] **Step 3: Add the path and dependency**

Add to `Config` and `ensure_dirs()`:

```python
model_secret_key_path: str = str(BASE_DIR / "data" / "model-settings.key")

Path(self.model_secret_key_path).parent.mkdir(parents=True, exist_ok=True)
```

Add `cryptography>=46.0` to project dependencies and document:

```dotenv
MODEL_SECRET_KEY_PATH=data/model-settings.key
```

- [ ] **Step 4: Verify the configuration test passes**

Run the same targeted pytest command. Expected: PASS.

- [ ] **Step 5: Commit the configuration change**

```powershell
git add config.py pyproject.toml .env.example tests/test_config.py
git commit -m "feat: configure encrypted model settings"
```

## Task 2: Encrypted Model Settings Store

**Files:**
- Create: `models/model_settings.py`
- Create: `tests/test_model_settings.py`

- [ ] **Step 1: Write failing tests for encrypted profiles**

Cover creation, redaction, key retention, and explicit clearing:

```python
def test_profile_secret_is_encrypted_and_never_returned(settings_store):
    profile = settings_store.create_profile(
        name="DeepSeek",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-secret-value",
        chat_models=["deepseek-chat"],
        embedding_models=[],
    )
    raw = settings_store._get_profile_row(profile["id"])
    assert b"sk-secret-value" not in raw["api_key_encrypted"]
    assert profile["has_api_key"] is True
    assert profile["api_key_masked"].endswith("alue")
    assert "api_key" not in profile


def test_update_without_key_preserves_existing_secret(settings_store):
    created = create_profile(settings_store, api_key="sk-original")
    settings_store.update_profile(created["id"], name="Renamed", api_key="")
    assert settings_store.get_profile_secret(created["id"]) == "sk-original"


def test_explicit_clear_removes_secret(settings_store):
    created = create_profile(settings_store, api_key="sk-original")
    updated = settings_store.update_profile(created["id"], clear_api_key=True)
    assert updated["has_api_key"] is False


def test_missing_master_key_does_not_replace_key_for_existing_ciphertext(settings_store):
    created = create_profile(settings_store, api_key="sk-original")
    settings_store.key_path.unlink()
    reopened = ModelSettingsStore(settings_store.config)
    with pytest.raises(ModelSecretError, match="主密钥"):
        reopened.get_profile_secret(created["id"])
    assert not settings_store.key_path.exists()
```

- [ ] **Step 2: Run tests and confirm the module is missing**

```powershell
uv run --isolated --with ".[dev]" pytest tests/test_model_settings.py -vv
```

Expected: collection ERROR for missing `models.model_settings`.

- [ ] **Step 3: Implement provider templates and encrypted profiles**

Implement these public contracts in `models/model_settings.py`:

```python
ProviderName = Literal["openai", "anthropic", "deepseek", "qwen", "openai_compatible"]
RoutePurpose = Literal["creative", "analysis", "embedding"]

PROVIDER_TEMPLATES: dict[str, dict[str, object]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "chat_models": ["gpt-4o", "gpt-4.1", "gpt-5"],
        "embedding_models": ["text-embedding-3-small", "text-embedding-3-large"],
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url": "",
        "chat_models": ["claude-sonnet-4-5", "claude-opus-4-1"],
        "embedding_models": [],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "chat_models": ["deepseek-chat", "deepseek-reasoner"],
        "embedding_models": [],
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_models": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "embedding_models": ["text-embedding-v3"],
    },
    "openai_compatible": {
        "label": "OpenAI Compatible",
        "base_url": "",
        "chat_models": [],
        "embedding_models": [],
    },
}

```

The required method signatures are:

- `create_profile(*, name: str, provider: ProviderName, base_url: str, api_key: str, chat_models: list[str], embedding_models: list[str]) -> dict`
- `update_profile(profile_id: str, *, name: str | None = None, provider: ProviderName | None = None, base_url: str | None = None, api_key: str = "", clear_api_key: bool = False, chat_models: list[str] | None = None, embedding_models: list[str] | None = None) -> dict`
- `list_profiles() -> list[dict]`
- `get_public_profile(profile_id: str) -> dict | None`
- `get_profile_secret(profile_id: str) -> str`
- `delete_profile(profile_id: str) -> bool`

Use `Fernet.generate_key()` only when saving the first secret. Write the key to a temporary sibling file and atomically replace the target. If encrypted rows exist and the key file is absent or invalid, raise `ModelSecretError` without generating a replacement.

- [ ] **Step 4: Verify profile tests pass**

Run `pytest tests/test_model_settings.py -vv`. Expected: profile tests PASS.

- [ ] **Step 5: Add failing route transaction tests**

```python
def test_routes_update_atomically_and_block_profile_deletion(settings_store):
    chat = create_profile(settings_store, name="Chat", provider="openai")
    embed = create_profile(settings_store, name="Embed", provider="qwen")
    routes = settings_store.save_routes({
        "creative": {"profile_id": chat["id"], "model_name": "gpt-4.1"},
        "analysis": {"profile_id": chat["id"], "model_name": "gpt-4o"},
        "embedding": {"profile_id": embed["id"], "model_name": "text-embedding-v3"},
    })
    assert set(routes) == {"creative", "analysis", "embedding"}
    with pytest.raises(ProfileInUseError):
        settings_store.delete_profile(chat["id"])


def test_anthropic_cannot_be_embedding_route(settings_store):
    anthropic = create_profile(settings_store, provider="anthropic")
    with pytest.raises(InvalidModelRouteError, match="嵌入"):
        settings_store.save_routes(three_routes_using(anthropic["id"]))
```

- [ ] **Step 6: Implement route validation and transactions**

Add `save_routes()`, `get_routes()`, `get_public_settings()`, `ProfileInUseError`, and `InvalidModelRouteError`. Validate all three routes before opening the write transaction, then upsert all three in one transaction.

- [ ] **Step 7: Run store tests and commit**

```powershell
uv run --isolated --with ".[dev]" pytest tests/test_model_settings.py -vv
git add models/model_settings.py tests/test_model_settings.py
git commit -m "feat: persist encrypted model profiles"
```

## Task 3: Runtime Model Resolver

**Files:**
- Create: `models/resolver.py`
- Create: `tests/test_model_resolver.py`
- Modify: `models/llm.py`
- Modify: `memory/vector_store.py`

- [ ] **Step 1: Write failing resolution tests**

Use monkeypatched constructors to assert protocol mapping without network calls:

```python
def test_deepseek_route_builds_openai_compatible_chat(settings_store, monkeypatch):
    profile = create_and_route(settings_store, provider="deepseek", purpose="creative")
    captured = {}
    monkeypatch.setattr("models.resolver.ChatOpenAI", lambda **kwargs: captured.update(kwargs) or object())
    ModelResolver(store=settings_store).chat("creative", temperature=0.8)
    assert captured["model"] == profile["chat_models"][0]
    assert captured["base_url"] == "https://api.deepseek.com"


def test_anthropic_route_builds_native_client(settings_store, monkeypatch):
    captured = {}
    monkeypatch.setattr("models.resolver.ChatAnthropic", lambda **kwargs: captured.update(kwargs) or object())
    configure_anthropic_analysis(settings_store)
    ModelResolver(store=settings_store).chat("analysis", temperature=0.3)
    assert captured["model"].startswith("claude-")
    assert "anthropic_api_key" in captured


def test_updated_route_does_not_reuse_old_client(settings_store, monkeypatch):
    built = []
    monkeypatch.setattr("models.resolver._build_openai_chat", lambda resolved, **kw: built.append(resolved.model_name) or object())
    resolver = ModelResolver(store=settings_store)
    resolver.chat("creative")
    change_creative_model(settings_store, "gpt-4.1")
    resolver.chat("creative")
    assert built == ["gpt-4o", "gpt-4.1"]
```

- [ ] **Step 2: Confirm resolver tests fail**

Run `pytest tests/test_model_resolver.py -vv`. Expected: missing resolver module.

- [ ] **Step 3: Implement the resolver and cached factories**

Define the frozen value object below:

```python
@dataclass(frozen=True)
class ResolvedModel:
    purpose: RoutePurpose
    provider: ProviderName
    model_name: str
    base_url: str
    api_key: str
    max_tokens: int
    source: Literal["database", "environment"]

```

`ModelResolver` must expose these exact methods:

- `resolve(purpose: RoutePurpose) -> ResolvedModel`
- `validate_runtime() -> None`
- `chat(purpose: Literal["creative", "analysis"], temperature: float | None = None, model_name: str | None = None, streaming: bool = True) -> BaseChatModel`
- `embeddings() -> Embeddings`
- `test_profile(profile_id: str, kind: Literal["chat", "embedding"], model_name: str) -> dict[str, object]`

Keep caching inside factories keyed by the full frozen `ResolvedModel`, temperature, and streaming flag. Do not decorate `get_llm()` or `ModelResolver.resolve()` with `lru_cache`.

Environment fallback maps `Config.llm_provider/model_name` to creative and analysis, and maps `Config.openai_api_key/embedding_model` to embedding. Raise `ModelConfigurationError` with purpose-specific Chinese messages when a required key or route is missing.

- [ ] **Step 4: Delegate existing model entry points**

Preserve call-site compatibility:

```python
def get_llm(
    temperature: float | None = None,
    model_name: str | None = None,
    streaming: bool = True,
    purpose: Literal["creative", "analysis"] = "creative",
) -> BaseChatModel:
    return ModelResolver().chat(purpose, temperature, model_name, streaming)


def get_analyzer_llm() -> BaseChatModel:
    return get_llm(temperature=0.3, purpose="analysis")
```

Change `NovelMemory` to call `ModelResolver(config=self.config).embeddings()` instead of constructing `OpenAIEmbeddings` directly.

- [ ] **Step 5: Verify resolver and existing agent tests**

```powershell
uv run --isolated --with ".[dev]" pytest tests/test_model_resolver.py tests/test_structured_agents.py tests/test_graph_flow.py -vv
```

Expected: all selected tests PASS.

- [ ] **Step 6: Commit runtime routing**

```powershell
git add models/resolver.py models/llm.py memory/vector_store.py tests/test_model_resolver.py
git commit -m "feat: route agents through selected models"
```

## Task 4: Model Settings API

**Files:**
- Create: `api/model_settings.py`
- Modify: `api/server.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Extend the isolated API fixture**

Ensure lifespan builds a `ModelSettingsStore(cfg)` against each test's temporary SQLite and exposes it through `app.state.model_settings_store`.

- [ ] **Step 2: Write failing CRUD and redaction API tests**

```python
async def test_model_profile_api_never_returns_plaintext_key(api_env):
    async with api_client(api_env) as client:
        created = await client.post("/api/model-settings/profiles", json={
            "name": "DeepSeek",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-api-secret",
            "chat_models": ["deepseek-chat"],
            "embedding_models": [],
        })
        listed = await client.get("/api/model-settings")
    assert created.status_code == 201
    assert "sk-api-secret" not in created.text
    assert "sk-api-secret" not in listed.text
    assert created.json()["has_api_key"] is True


async def test_delete_routed_profile_returns_409(api_env):
    profile_id = await create_profile_via_api(api_env)
    await save_three_routes_via_api(api_env, profile_id)
    response = await delete_profile_via_api(api_env, profile_id)
    assert response.status_code == 409
```

- [ ] **Step 3: Confirm API tests fail with 404**

Run the two new tests. Expected: FAIL because `/api/model-settings` routes do not exist.

- [ ] **Step 4: Implement the dedicated router**

Create request models with bounded strings and URL validation:

```python
class ProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: ProviderName
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    chat_models: list[str] = Field(default_factory=list, max_length=50)
    embedding_models: list[str] = Field(default_factory=list, max_length=50)

class RouteTarget(BaseModel):
    profile_id: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=200)

class RoutesWrite(BaseModel):
    creative: RouteTarget
    analysis: RouteTarget
    embedding: RouteTarget
```

Use `Request.app.state.model_settings_store`; translate missing profiles to 404, invalid routes to 422, and `ProfileInUseError` to 409. Register the router in `api/server.py` and allow `PUT` in CORS.

- [ ] **Step 5: Add active-stream conflict tests**

```python
async def test_settings_write_returns_409_during_graph_stream(api_env):
    api_env.app.state.active_streams = 1
    async with api_client(api_env) as client:
        response = await client.put("/api/model-settings/routes", json=valid_routes_payload())
    assert response.status_code == 409
```

- [ ] **Step 6: Track active streams and enforce the conflict**

Initialize `active_streams = 0` in lifespan. Increment immediately before returning a graph `StreamingResponse`, decrement in `_stream_graph`'s `finally`, and reject every settings mutation while the count is nonzero. Read-only settings requests remain available.

- [ ] **Step 7: Implement connection-test endpoint with mocks**

Patch `ModelResolver.test_profile()` in tests to cover successful chat, successful embedding, sanitized authentication failure, and sanitized network failure. Return:

```json
{"ok": true, "latency_ms": 42, "message": "连接成功"}
```

Do not return raw exception representations.

- [ ] **Step 8: Run API tests and commit**

```powershell
uv run --isolated --with ".[dev]" pytest tests/test_api.py tests/test_model_settings.py -vv
git add api/model_settings.py api/server.py tests/test_api.py
git commit -m "feat: expose redacted model settings api"
```

## Task 5: Runtime Preflight And Error Semantics

**Files:**
- Modify: `api/server.py`
- Modify: `main.py`
- Modify: `ui/streamlit_app.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing API preflight tests**

```python
async def test_run_rejects_missing_model_configuration_before_stream(api_env, monkeypatch):
    monkeypatch.setattr(
        "api.server.ModelResolver.validate_runtime",
        lambda self: (_ for _ in ()).throw(ModelConfigurationError("未配置创作模型")),
    )
    response = await create_then_run(api_env)
    assert response.status_code == 409
    assert response.json()["detail"] == "未配置创作模型"
```

Add the same expectation for `/resume` so a paused graph remains untouched after preflight failure.

- [ ] **Step 2: Confirm tests fail because run starts streaming**

Run the two targeted tests. Expected: status differs from 409.

- [ ] **Step 3: Validate immediately after acquiring each novel lock**

Instantiate `ModelResolver(config=cfg, store=app.state.model_settings_store)` and call `validate_runtime()` before reading or driving graph state. Translate `ModelConfigurationError` to HTTP 409 and release the novel lock through the existing exception path.

- [ ] **Step 4: Add CLI and Streamlit diagnostics**

At startup, validate configuration before generating or resuming. CLI exits through `parser.error()` with the resolver message. Streamlit renders the message and directs the user to the React workbench settings without deleting or changing checkpoints.

- [ ] **Step 5: Run entry-point tests and commit**

```powershell
uv run --isolated --with ".[dev]" pytest tests/test_api.py tests/test_cli.py tests/test_ui_runtime.py -vv
git add api/server.py main.py ui/streamlit_app.py tests/test_api.py tests/test_cli.py
git commit -m "fix: validate model routes before generation"
```

## Task 6: Frontend Settings Data Layer

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/useModelSettings.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/useModelSettings.test.tsx`

- [ ] **Step 1: Add the frontend test runner**

Install `vitest`, `jsdom`, `@testing-library/react`, and `@testing-library/user-event` as dev dependencies. Add:

```json
"test": "vitest run",
"test:watch": "vitest"
```

Configure Vitest with `environment: "jsdom"` in `vite.config.ts`.

- [ ] **Step 2: Define the public TypeScript contract**

Add exact interfaces matching the API:

```typescript
export type ProviderName = "openai" | "anthropic" | "deepseek" | "qwen" | "openai_compatible";
export type RoutePurpose = "creative" | "analysis" | "embedding";

export interface ModelProfile {
  id: string;
  name: string;
  provider: ProviderName;
  base_url: string;
  has_api_key: boolean;
  api_key_masked: string;
  chat_models: string[];
  embedding_models: string[];
}

export interface ModelRoute {
  profile_id: string;
  model_name: string;
}

export interface ModelSettings {
  source: "database" | "environment" | "unconfigured";
  templates: Record<ProviderName, ProviderTemplate>;
  profiles: ModelProfile[];
  routes: Partial<Record<RoutePurpose, ModelRoute>>;
}
```

- [ ] **Step 3: Write failing hook tests**

Mock only the HTTP module and verify real hook state transitions:

```typescript
it("reloads redacted settings after saving a profile", async () => {
  vi.mocked(getModelSettings).mockResolvedValueOnce(emptySettings).mockResolvedValueOnce(savedSettings);
  const { result } = renderHook(() => useModelSettings(true));
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  await act(() => result.current.saveProfile(profileDraft));
  expect(result.current.settings?.profiles[0].has_api_key).toBe(true);
});
```

- [ ] **Step 4: Confirm hook tests fail**

```powershell
npm.cmd --prefix frontend test -- useModelSettings.test.tsx
```

Expected: FAIL because the hook and API functions are missing.

- [ ] **Step 5: Implement API functions and hook**

Add `getModelSettings`, `createModelProfile`, `updateModelProfile`, `deleteModelProfile`, `saveModelRoutes`, and `testModelProfile`. The hook owns loading, saving, testing, deleting, route-saving, error, and last success message state. Reload settings after every successful mutation.

- [ ] **Step 6: Run hook tests and commit**

```powershell
npm.cmd --prefix frontend test -- useModelSettings.test.tsx
git add frontend/src/types.ts frontend/src/api.ts frontend/src/useModelSettings.ts frontend/src/useModelSettings.test.tsx frontend/package.json frontend/package-lock.json frontend/vite.config.ts
git commit -m "feat: add model settings client state"
```

## Task 7: Model Settings Workbench UI

**Files:**
- Create: `frontend/src/components/ModelSettingsDialog.tsx`
- Create: `frontend/src/components/ModelProfilesPanel.tsx`
- Create: `frontend/src/components/ModelRoutesPanel.tsx`
- Create: `frontend/src/components/ModelSettingsDialog.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing dialog interaction tests**

Cover opening, redacted key behavior, save, route tab, and running-state disabling:

```typescript
it("does not submit the masked key as a replacement secret", async () => {
  render(<ModelSettingsDialog open settings={configuredSettings} onClose={noop} actions={actions} />);
  await user.click(screen.getByRole("button", { name: "保存服务" }));
  expect(actions.saveProfile).toHaveBeenCalledWith(expect.objectContaining({ api_key: "" }));
});


it("disables all mutations while a novel is running", () => {
  render(<ModelSettingsDialog open isStreaming settings={configuredSettings} onClose={noop} actions={actions} />);
  expect(screen.getByRole("button", { name: "保存服务" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "保存模型分工" })).toBeDisabled();
});
```

- [ ] **Step 2: Confirm component tests fail**

Run `npm.cmd --prefix frontend test -- ModelSettingsDialog.test.tsx`. Expected: missing component failure.

- [ ] **Step 3: Build the dialog shell and entry point**

Add a `Settings` icon button from Lucide to the topbar with `title="模型设置"`. Render an accessible dialog with `role="dialog"`, `aria-modal="true"`, Escape-to-close, backdrop click, focusable close button, and two tabs named “模型服务” and “模型分工”. Keep the dialog mounted only while open so secret inputs are discarded on close.

- [ ] **Step 4: Implement the profile editor**

Use native controls appropriate to the data:

- provider `<select>` using templates;
- name and base URL inputs;
- password input that starts empty even when a key exists;
- model names as comma/newline-normalized editable lists;
- icon buttons for add/delete and text buttons for test/save commands;
- explicit configured badge and success/error callouts.

Deleting requires `window.confirm`. Choosing a built-in provider pre-fills template values only for a new profile and never overwrites an existing edited profile.

- [ ] **Step 5: Implement route selectors**

Each purpose row contains a profile selector and an editable model selector. Filter embedding profiles to non-Anthropic profiles. Disable “保存模型分工” until all three targets are valid.

- [ ] **Step 6: Add responsive styling**

Use a square-cornered, maximum `960px` dialog with stable grid tracks. At widths below `760px`, stack the profile list above the editor and keep dialog content scrollable within `100dvh`. Do not introduce nested cards, gradients, decorative blobs, or viewport-scaled font sizes.

- [ ] **Step 7: Run component tests, typecheck, and build**

```powershell
npm.cmd --prefix frontend test -- ModelSettingsDialog.test.tsx
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit the workbench UI**

```powershell
git add frontend/src/components/ModelSettingsDialog.tsx frontend/src/components/ModelProfilesPanel.tsx frontend/src/components/ModelRoutesPanel.tsx frontend/src/components/ModelSettingsDialog.test.tsx frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: manage model providers in workbench"
```

## Task 8: Documentation, CI, And Deployment

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Document the model settings workflow**

Explain provider profiles, the three model roles, redacted-key behavior, environment fallback, `MODEL_SECRET_KEY_PATH`, and the consequence of losing the master key. State that `data/` must be backed up together with `memory/novels.db`.

- [ ] **Step 2: Persist the master-key directory in containers**

Ensure Docker Compose mounts the same persistent data volume/path used by `MODEL_SECRET_KEY_PATH`. Confirm `.gitignore` includes `data/` and `*.key` without ignoring source fixtures.

- [ ] **Step 3: Add frontend tests to CI**

After `npm ci`, run:

```yaml
- run: npm --prefix frontend test
- run: npm --prefix frontend run typecheck
- run: npm --prefix frontend run build
```

- [ ] **Step 4: Run focused documentation and configuration checks**

```powershell
rg -n "MODEL_SECRET_KEY_PATH|模型服务|模型分工|环境配置回退" README.md .env.example docker-compose.yml
git diff --check
```

Expected: each term is documented and `git diff --check` exits 0.

- [ ] **Step 5: Commit docs and deployment changes**

```powershell
git add README.md .github/workflows/ci.yml Dockerfile docker-compose.yml .gitignore
git commit -m "docs: document workbench model settings"
```

## Task 9: Full Verification And Browser QA

**Files:**
- No planned source changes; fix only failures directly caused by this feature.

- [ ] **Step 1: Run the complete backend suite**

```powershell
uv run --isolated --with ".[dev]" pytest -q
uvx ruff check agents graph memory tools prompts models api ui config.py main.py tests scripts
python -m compileall -q agents api graph memory models prompts tools ui config.py main.py
```

Expected: all tests pass, Ruff reports “All checks passed!”, and compileall exits 0.

- [ ] **Step 2: Run the complete frontend suite**

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
```

Expected: Vitest, TypeScript, and Vite all exit 0.

- [ ] **Step 3: Run browser QA at desktop and mobile widths**

Start FastAPI and Vite, then verify through the browser:

1. Open model settings from the topbar.
2. Create OpenAI-compatible and Anthropic profiles.
3. Confirm saved keys reload only as masked status.
4. Save creative, analysis, and embedding routes.
5. Refresh and confirm routes persist.
6. Confirm routed profiles cannot be deleted.
7. Start a novel and confirm mutation controls are disabled.
8. Check `1440x900`, `768x1024`, and `390x844` for overflow and overlap.
9. Confirm the browser console contains no errors.

- [ ] **Step 4: Build the container**

```powershell
docker build -t novel-agent:test .
docker compose config
```

Expected: image build and Compose validation succeed. If Docker is unavailable, record that exact limitation without claiming container verification.

- [ ] **Step 5: Inspect the final diff and security invariants**

```powershell
git diff --check
rg -n "api_key" api models frontend/src tests
git status --short
```

Manually confirm no API response model exposes `api_key`, no log statement includes secrets, no runtime `.key` or SQLite file is staged, and only intended feature files changed.

- [ ] **Step 6: Commit any verification-only fixes**

If verification required source fixes, stage only those exact files and commit with a message describing the verified defect. If no fixes were needed, do not create an empty commit.
