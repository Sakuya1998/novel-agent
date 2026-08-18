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


def test_fallback_route_is_persisted_and_blocks_profile_deletion(settings_store):
    primary = create_profile(settings_store, name="Primary")
    fallback = create_profile(settings_store, name="Fallback")
    embed = create_profile(settings_store, name="Embed", provider="qwen")
    routes = valid_routes(primary["id"], embed["id"])
    routes["creative"].update({
        "fallback_profile_id": fallback["id"],
        "fallback_model_name": "gpt-4o",
    })

    saved = settings_store.save_routes(routes)

    assert saved["creative"]["fallback_profile_id"] == fallback["id"]
    with pytest.raises(ProfileInUseError):
        settings_store.delete_profile(fallback["id"])


def test_model_usage_can_be_aggregated_and_deleted(settings_store):
    settings_store.record_model_call(
        novel_id="novel_1",
        agent="scene_writer",
        purpose="creative",
        provider="openai",
        model_name="gpt-4o",
        attempt=1,
        fallback_used=False,
        success=True,
        duration_ms=25,
        input_tokens=10,
        output_tokens=20,
        usage_estimated=False,
    )

    usage = settings_store.get_model_usage("novel_1")
    assert usage["total_tokens"] == 30
    assert usage["duration_ms"] == 25
    assert usage["by_agent"][0]["agent"] == "scene_writer"

    settings_store.delete_novel_metrics("novel_1")
    assert settings_store.get_model_usage("novel_1")["attempts"] == 0
    assert settings_store.list_model_traces("novel_1") == []


def test_model_traces_can_filter_by_agent_without_returning_content(settings_store):
    settings_store.record_model_call(
        novel_id="novel_1",
        agent="scene_writer",
        purpose="creative",
        provider="openai",
        model_name="gpt-4o",
        attempt=1,
        fallback_used=False,
        success=True,
        duration_ms=12,
        input_tokens=3,
        output_tokens=4,
        usage_estimated=True,
        call_id="call-1",
        trace_id="trace-1",
        input_hash="input-hash",
        output_hash="output-hash",
        input_chars=20,
        output_chars=30,
    )
    settings_store.record_model_call(
        novel_id="novel_1",
        agent="style_editor",
        purpose="creative",
        provider="openai",
        model_name="gpt-4o",
        attempt=1,
        fallback_used=False,
        success=False,
        duration_ms=8,
        input_tokens=3,
        output_tokens=0,
        usage_estimated=True,
        error_type="TimeoutError",
        call_id="call-2",
        trace_id="trace-2",
        input_hash="other-input",
        input_chars=8,
    )

    traces = settings_store.list_model_traces("novel_1", agent="scene_writer")
    assert len(traces) == 1
    assert traces[0]["trace_id"] == "trace-1"
    assert traces[0]["success"] is True
    assert traces[0]["usage_estimated"] is True
    assert "input" not in traces[0]
    assert "output" not in traces[0]


def test_legacy_model_metrics_table_is_migrated_for_traces(tmp_path):
    db_path = tmp_path / "legacy-model-metrics.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE model_call_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id TEXT,
                agent TEXT NOT NULL,
                purpose TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_name TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                success INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                usage_estimated INTEGER NOT NULL DEFAULT 0,
                error_type TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
    cfg = Config(
        sqlite_db_path=str(db_path),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
    )
    store = ModelSettingsStore(cfg)

    store.record_model_call(
        novel_id="novel_legacy",
        agent="scene_writer",
        purpose="creative",
        provider="openai",
        model_name="gpt-test",
        attempt=1,
        fallback_used=False,
        success=True,
        duration_ms=1,
        input_tokens=1,
        output_tokens=1,
        usage_estimated=False,
        trace_id="trace-migrated",
    )

    assert store.list_model_traces("novel_legacy")[0]["trace_id"] == "trace-migrated"


def test_model_profiles_and_routes_are_tenant_scoped(settings_store):
    from security import Principal, reset_current_principal, set_current_principal

    alice = Principal("user-a", "tenant-a", "alice", "owner")
    bob = Principal("user-b", "tenant-b", "bob", "owner")
    alice_token = set_current_principal(alice)
    try:
        profile = settings_store.create_profile(
            name="共享名称",
            provider="openai",
            base_url="",
            api_key="key-a",
            chat_models=["gpt-a"],
            embedding_models=["embed-a"],
        )
        settings_store.save_routes({
            "creative": {"profile_id": profile["id"], "model_name": "gpt-a"},
            "analysis": {"profile_id": profile["id"], "model_name": "gpt-a"},
            "embedding": {"profile_id": profile["id"], "model_name": "embed-a"},
        })
    finally:
        reset_current_principal(alice_token)

    bob_token = set_current_principal(bob)
    try:
        assert settings_store.list_profiles() == []
        assert settings_store.get_routes() == {}
        bob_profile = settings_store.create_profile(
            name="共享名称",
            provider="openai",
            base_url="",
            api_key="key-b",
            chat_models=["gpt-b"],
            embedding_models=["embed-b"],
        )
        assert bob_profile["id"] != profile["id"]
    finally:
        reset_current_principal(bob_token)


def test_legacy_model_routes_are_migrated_to_local_tenant(tmp_path):
    db_path = tmp_path / "legacy-model-routes.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE model_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
            "provider TEXT NOT NULL, base_url TEXT NOT NULL DEFAULT '', "
            "api_key_encrypted BLOB NOT NULL DEFAULT X'', chat_models_json TEXT NOT NULL DEFAULT '[]', "
            "embedding_models_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE model_routes (purpose TEXT PRIMARY KEY, profile_id TEXT NOT NULL, "
            "model_name TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO model_profiles VALUES ('p1', 'Legacy', 'openai', '', X'', '[]', '[]', 'now', 'now')"
        )
        conn.execute("INSERT INTO model_routes VALUES ('creative', 'p1', 'gpt-old', 'now')")
    cfg = Config(
        sqlite_db_path=str(db_path),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
    )
    store = ModelSettingsStore(cfg)

    assert store.get_routes()["creative"]["model_name"] == "gpt-old"
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(model_routes)")}
    assert "tenant_id" in columns
