"""全局模型路由解析与 LangChain 客户端构造测试。"""

import pytest

from config import Config
from models.model_settings import ModelSettingsStore
from models.resolver import (
    ModelConfigurationError,
    ModelConnectionError,
    ModelResolver,
    sanitize_provider_error,
)


@pytest.fixture
def resolver_env(tmp_path):
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "data" / "model-settings.key"),
        openai_api_key="env-openai-key",
        anthropic_api_key="env-anthropic-key",
        model_name="gpt-4o",
        embedding_model="text-embedding-3-small",
    )
    return cfg, ModelSettingsStore(cfg)


def add_profile(
    store: ModelSettingsStore,
    *,
    name: str,
    provider: str,
    base_url: str,
    chat_model: str,
    embedding_model: str = "embed-small",
) -> dict:
    return store.create_profile(
        name=name,
        provider=provider,
        base_url=base_url,
        api_key=f"key-{name}",
        chat_models=[chat_model],
        embedding_models=[] if provider == "anthropic" else [embedding_model],
    )


def save_routes(
    store: ModelSettingsStore,
    *,
    creative: tuple[str, str],
    analysis: tuple[str, str],
    embedding: tuple[str, str],
) -> None:
    store.save_routes({
        "creative": {"profile_id": creative[0], "model_name": creative[1]},
        "analysis": {"profile_id": analysis[0], "model_name": analysis[1]},
        "embedding": {"profile_id": embedding[0], "model_name": embedding[1]},
    })


def test_deepseek_route_builds_openai_compatible_chat(resolver_env, monkeypatch):
    cfg, store = resolver_env
    deepseek = add_profile(
        store,
        name="DeepSeek",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        chat_model="deepseek-chat",
    )
    save_routes(
        store,
        creative=(deepseek["id"], "deepseek-chat"),
        analysis=(deepseek["id"], "deepseek-reasoner"),
        embedding=(deepseek["id"], "embed-small"),
    )
    captured = {}
    monkeypatch.setattr(
        "models.resolver.ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    ModelResolver(config=cfg, store=store).chat("creative", temperature=0.8)

    assert captured["model"] == "deepseek-chat"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["api_key"] == "key-DeepSeek"


def test_anthropic_route_builds_native_client(resolver_env, monkeypatch):
    cfg, store = resolver_env
    claude = add_profile(
        store,
        name="Claude",
        provider="anthropic",
        base_url="",
        chat_model="claude-sonnet-4-5",
    )
    openai = add_profile(
        store,
        name="Embed",
        provider="openai",
        base_url="https://api.openai.com/v1",
        chat_model="gpt-4o",
    )
    save_routes(
        store,
        creative=(claude["id"], "claude-sonnet-4-5"),
        analysis=(claude["id"], "claude-opus-4-1"),
        embedding=(openai["id"], "text-embedding-3-small"),
    )
    captured = {}
    monkeypatch.setattr(
        "models.resolver.ChatAnthropic",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    ModelResolver(config=cfg, store=store).chat("analysis", temperature=0.3)

    assert captured["model"] == "claude-opus-4-1"
    assert captured["anthropic_api_key"] == "key-Claude"


def test_updated_route_does_not_reuse_old_client(resolver_env, monkeypatch):
    cfg, store = resolver_env
    profile = add_profile(
        store,
        name="OpenAI",
        provider="openai",
        base_url="https://api.openai.com/v1",
        chat_model="gpt-4o",
    )
    save_routes(
        store,
        creative=(profile["id"], "gpt-4o"),
        analysis=(profile["id"], "gpt-4o"),
        embedding=(profile["id"], "text-embedding-3-small"),
    )
    built: list[str] = []
    monkeypatch.setattr(
        "models.resolver.ChatOpenAI",
        lambda **kwargs: built.append(kwargs["model"]) or object(),
    )
    resolver = ModelResolver(config=cfg, store=store)

    resolver.chat("creative")
    save_routes(
        store,
        creative=(profile["id"], "gpt-4.1"),
        analysis=(profile["id"], "gpt-4o"),
        embedding=(profile["id"], "text-embedding-3-small"),
    )
    resolver.chat("creative")

    assert built == ["gpt-4o", "gpt-4.1"]


def test_qwen_embedding_uses_selected_base_url(resolver_env, monkeypatch):
    cfg, store = resolver_env
    qwen = add_profile(
        store,
        name="Qwen",
        provider="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        chat_model="qwen-plus",
        embedding_model="text-embedding-v3",
    )
    save_routes(
        store,
        creative=(qwen["id"], "qwen-plus"),
        analysis=(qwen["id"], "qwen-max"),
        embedding=(qwen["id"], "text-embedding-v3"),
    )
    captured = {}
    monkeypatch.setattr(
        "models.resolver.OpenAIEmbeddings",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    ModelResolver(config=cfg, store=store).embeddings()

    assert captured == {
        "model": "text-embedding-v3",
        "api_key": "key-Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }


def test_empty_database_falls_back_to_environment(resolver_env):
    cfg, store = resolver_env
    resolver = ModelResolver(config=cfg, store=store)

    creative = resolver.resolve("creative")
    embedding = resolver.resolve("embedding")

    assert creative.source == "environment"
    assert creative.model_name == "gpt-4o"
    assert creative.api_key == "env-openai-key"
    assert embedding.model_name == "text-embedding-3-small"


def test_validate_runtime_reports_missing_environment_key(tmp_path):
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
        openai_api_key="",
        anthropic_api_key="",
    )

    with pytest.raises(ModelConfigurationError, match="API Key"):
        ModelResolver(config=cfg, store=ModelSettingsStore(cfg)).validate_runtime()


def test_validate_runtime_rejects_anthropic_embedding_route(resolver_env):
    cfg, store = resolver_env
    profile = add_profile(
        store,
        name="OpenAI",
        provider="openai",
        base_url="https://api.openai.com/v1",
        chat_model="gpt-4o",
    )
    save_routes(
        store,
        creative=(profile["id"], "gpt-4o"),
        analysis=(profile["id"], "gpt-4o"),
        embedding=(profile["id"], "text-embedding-3-small"),
    )
    with store._conn() as conn:
        conn.execute(
            "UPDATE model_profiles SET provider = 'anthropic', base_url = '' WHERE id = ?",
            (profile["id"],),
        )

    with pytest.raises(ModelConfigurationError, match="嵌入"):
        ModelResolver(config=cfg, store=store).validate_runtime()


def test_provider_error_sanitizer_removes_known_and_labeled_secrets():
    error = RuntimeError(
        "request failed api_key=visible-key Authorization: Bearer bearer-key "
        "https://example.test?q=1&token=query-key naked-secret"
    )

    message = sanitize_provider_error(error, secrets=["naked-secret"])

    assert "visible-key" not in message
    assert "bearer-key" not in message
    assert "query-key" not in message
    assert "naked-secret" not in message


@pytest.mark.asyncio
async def test_connection_test_sanitizes_authentication_failure(resolver_env, monkeypatch):
    cfg, store = resolver_env
    profile = add_profile(
        store,
        name="OpenAI",
        provider="openai",
        base_url="https://api.openai.com/v1",
        chat_model="gpt-4o",
    )

    class FailingChat:
        async def ainvoke(self, prompt):
            raise RuntimeError("401 Unauthorized api_key=key-OpenAI")

    monkeypatch.setattr("models.resolver._build_openai_chat", lambda *args: FailingChat())

    with pytest.raises(ModelConnectionError, match="认证失败") as error:
        await ModelResolver(config=cfg, store=store).test_profile(
            profile["id"], "chat", "gpt-4o"
        )
    assert "key-OpenAI" not in str(error.value)


@pytest.mark.asyncio
async def test_connection_test_classifies_timeout(resolver_env, monkeypatch):
    cfg, store = resolver_env
    profile = add_profile(
        store,
        name="OpenAI",
        provider="openai",
        base_url="https://api.openai.com/v1",
        chat_model="gpt-4o",
    )

    class FailingChat:
        async def ainvoke(self, prompt):
            raise TimeoutError("request timed out")

    monkeypatch.setattr("models.resolver._build_openai_chat", lambda *args: FailingChat())

    with pytest.raises(ModelConnectionError, match="连接超时"):
        await ModelResolver(config=cfg, store=store).test_profile(
            profile["id"], "chat", "gpt-4o"
        )
