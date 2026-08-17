"""模型服务档案、密钥加密与全局路由测试。"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from config import Config
from models.model_settings import (
    InvalidModelRouteError,
    ModelSecretError,
    ModelSettingsStore,
    ProfileInUseError,
)


@pytest.fixture
def settings_store(tmp_path):
    cfg = Config(
        sqlite_db_path=str(tmp_path / "novels.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "data" / "model-settings.key"),
    )
    return ModelSettingsStore(cfg)


def create_profile(
    store: ModelSettingsStore,
    *,
    name: str = "OpenAI",
    provider: str = "openai",
    api_key: str = "sk-original",
) -> dict:
    models = ["claude-sonnet-4-5"] if provider == "anthropic" else ["gpt-4o"]
    return store.create_profile(
        name=name,
        provider=provider,
        base_url="" if provider == "anthropic" else "https://example.com/v1",
        api_key=api_key,
        chat_models=models,
        embedding_models=[] if provider == "anthropic" else ["embed-small"],
    )


def valid_routes(chat_profile_id: str, embedding_profile_id: str | None = None) -> dict:
    embedding_profile_id = embedding_profile_id or chat_profile_id
    return {
        "creative": {"profile_id": chat_profile_id, "model_name": "gpt-4o"},
        "analysis": {"profile_id": chat_profile_id, "model_name": "gpt-4o"},
        "embedding": {"profile_id": embedding_profile_id, "model_name": "embed-small"},
    }


def test_profile_secret_is_encrypted_and_never_returned(settings_store):
    profile = create_profile(settings_store, api_key="sk-secret-value")

    with sqlite3.connect(settings_store.db_path) as conn:
        encrypted = conn.execute(
            "SELECT api_key_encrypted FROM model_profiles WHERE id = ?", (profile["id"],)
        ).fetchone()[0]

    assert b"sk-secret-value" not in encrypted
    assert profile["has_api_key"] is True
    assert profile["api_key_masked"].endswith("alue")
    assert "api_key" not in profile


def test_update_without_key_preserves_existing_secret(settings_store):
    created = create_profile(settings_store)
    updated = settings_store.update_profile(created["id"], name="Renamed", api_key="")

    assert updated["name"] == "Renamed"
    assert settings_store.get_profile_secret(created["id"]) == "sk-original"


def test_explicit_clear_removes_secret(settings_store):
    created = create_profile(settings_store)
    updated = settings_store.update_profile(created["id"], clear_api_key=True)

    assert updated["has_api_key"] is False
    assert settings_store.get_profile_secret(created["id"]) == ""


def test_missing_master_key_does_not_replace_existing_key(settings_store):
    created = create_profile(settings_store)
    settings_store.key_path.unlink()

    reopened = ModelSettingsStore(settings_store.config)
    with pytest.raises(ModelSecretError, match="主密钥"):
        reopened.get_profile_secret(created["id"])
    assert not settings_store.key_path.exists()


def test_routes_update_atomically_and_block_profile_deletion(settings_store):
    chat = create_profile(settings_store, name="Chat")
    embed = create_profile(settings_store, name="Embed", provider="qwen")

    routes = settings_store.save_routes(valid_routes(chat["id"], embed["id"]))

    assert set(routes) == {"creative", "analysis", "embedding"}
    with pytest.raises(ProfileInUseError):
        settings_store.delete_profile(chat["id"])


def test_anthropic_cannot_be_embedding_route_and_old_routes_survive(settings_store):
    chat = create_profile(settings_store, name="Chat")
    anthropic = create_profile(settings_store, name="Claude", provider="anthropic")
    original = settings_store.save_routes(valid_routes(chat["id"]))
    invalid = valid_routes(chat["id"], anthropic["id"])

    with pytest.raises(InvalidModelRouteError, match="嵌入"):
        settings_store.save_routes(invalid)

    assert settings_store.get_routes() == original


def test_routed_embedding_profile_cannot_be_changed_to_anthropic(settings_store):
    profile = create_profile(settings_store)
    settings_store.save_routes(valid_routes(profile["id"]))

    with pytest.raises(ProfileInUseError, match="嵌入"):
        settings_store.update_profile(profile["id"], provider="anthropic", base_url="")

    assert settings_store.get_public_profile(profile["id"])["provider"] == "openai"


def test_concurrent_first_secret_saves_share_one_master_key(settings_store, monkeypatch):
    barrier = Barrier(2)
    original_generate = __import__(
        "models.model_settings", fromlist=["Fernet"]
    ).Fernet.generate_key

    def synchronized_generate():
        key = original_generate()
        barrier.wait(timeout=5)
        return key

    monkeypatch.setattr(
        "models.model_settings.Fernet.generate_key",
        synchronized_generate,
    )
    stores = [ModelSettingsStore(settings_store.config), ModelSettingsStore(settings_store.config)]

    with ThreadPoolExecutor(max_workers=2) as executor:
        fernets = list(executor.map(lambda store: store._read_fernet(create=True), stores))

    winner = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet(
        settings_store.key_path.read_bytes().strip()
    )
    for fernet in fernets:
        assert fernet is not None
        assert winner.decrypt(fernet.encrypt(b"shared")) == b"shared"


def test_public_settings_include_templates_and_database_source(settings_store):
    profile = create_profile(settings_store)
    settings_store.save_routes(valid_routes(profile["id"]))

    public = settings_store.get_public_settings()

    assert public["source"] == "database"
    assert "deepseek" in public["templates"]
    assert public["profiles"][0]["has_api_key"] is True
    assert "api_key" not in public["profiles"][0]
