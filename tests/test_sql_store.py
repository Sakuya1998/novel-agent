"""SQLite 结构化存储测试。"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from config import Config
from memory.sql_store import NovelStore


def test_novel_crud(store):
    created = store.create_novel(
        "n1",
        "雾中剑",
        genre="武侠",
        style="gu_long",
        total_chapters=3,
        inspiration="灵感",
        planning_review_enabled=True,
        creative_brief={
            "target_audience": "成年武侠读者",
            "ending_tone": "bittersweet",
            "themes": ["选择与代价"],
        },
    )
    assert created["id"] == "n1"
    assert created["planning_review_enabled"] is True
    assert created["creative_brief_version"] == 1
    assert created["creative_brief"]["ending_tone"] == "bittersweet"

    got = store.get_novel("n1")
    assert got["title"] == "雾中剑"
    assert got["inspiration"] == "灵感"
    assert got["planning_review_enabled"] is True
    assert got["creative_brief"]["target_audience"] == "成年武侠读者"
    assert got["creative_brief"]["themes"] == ["选择与代价"]
    assert store.list_creative_brief_versions("n1")[0]["source"] == "created"

    assert store.get_novel("missing") is None
    assert [n["id"] for n in store.list_novels()] == ["n1"]


def test_schema_migration_ledger_records_current_versions(store):
    from models.model_settings import ModelSettingsStore

    ModelSettingsStore(store.config)
    versions = store.get_schema_versions()
    assert versions[NovelStore.SCHEMA_COMPONENT] == NovelStore.SCHEMA_VERSION
    assert versions[ModelSettingsStore.SCHEMA_COMPONENT] == ModelSettingsStore.SCHEMA_VERSION


def test_chapter_upsert_idempotent(store):
    store.create_novel("n1", "书")
    rid1 = store.save_chapter(
        "n1",
        1,
        "雾起",
        "第一章内容",
        "摘要",
        "draft",
        scene_plan=[{"scene_number": 1, "goal": "入城"}],
    )
    rid2 = store.save_chapter(
        "n1",
        1,
        "雾起(改)",
        "第一章内容改",
        "摘要改",
        "final",
        scene_plan=[{"scene_number": 1, "goal": "改道入城"}],
    )
    assert rid1 == rid2  # 同 novel+chapter 幂等更新

    ch = store.get_chapter("n1", 1)
    assert ch["title"] == "雾起(改)"
    assert ch["status"] == "final"
    assert ch["word_count"] == len("第一章内容改")
    assert ch["scene_plan"] == [{"scene_number": 1, "goal": "改道入城"}]

    chapters = store.get_all_chapters("n1")
    assert len(chapters) == 1


def test_chapter_isolation_between_novels(store):
    store.create_novel("a", "甲书")
    store.create_novel("b", "乙书")
    store.save_chapter("a", 1, "甲一章", "内容")
    store.save_chapter("b", 1, "乙一章", "内容")
    assert store.get_chapter("a", 1)["title"] == "甲一章"
    assert len(store.get_all_chapters("b")) == 1


def test_progress_roundtrip(store):
    store.create_novel("n1", "书")
    store.save_progress("n1", current_chapter=2, current_phase="writing", state={"chapters": ["c1"]})

    p = store.get_progress("n1")
    assert p["current_chapter"] == 2
    assert p["current_phase"] == "writing"
    assert p["state"] == {"chapters": ["c1"]}

    # 更新覆盖
    store.save_progress("n1", current_chapter=3, current_phase="style_editing")
    assert store.get_progress("n1")["current_chapter"] == 3


def test_delete_novel_removes_novel_chapters_and_progress(store):
    store.create_novel("delete-me", "待删除", total_chapters=1)
    store.save_chapter("delete-me", 1, "第一章", "正文", status="final")
    store.save_progress("delete-me", 2, "writing", {"current_chapter": 2})

    assert store.delete_novel("delete-me") is True
    assert store.get_novel("delete-me") is None
    assert store.get_all_chapters("delete-me") == []
    assert store.get_progress("delete-me") is None
    assert store.delete_novel("delete-me") is False


def test_legacy_chapter_table_is_migrated_for_scene_plans(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id TEXT,
                chapter_number INTEGER,
                title TEXT,
                content TEXT,
                summary TEXT,
                word_count INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(novel_id, chapter_number)
            )
        """)

    cfg = Config(
        sqlite_db_path=str(db_path),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
    )
    migrated = NovelStore(cfg)

    with sqlite3.connect(migrated.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(chapters)")}
    assert "scene_plan_json" in columns
    assert "digest_json" in columns


def test_chapter_digest_round_trips_and_hydrates_canon_fields(store):
    store.create_novel("n1", "书")
    digest = {
        "summary": "正文实际摘要",
        "events": ["主角发现密门"],
        "characters": ["沈砚"],
        "locations": ["旧宅"],
        "emotion": "惊疑",
        "extracted_facts": [
            {"kind": "revelation", "subject": "密门", "value": "通往地下档案室"}
        ],
        "digest_version": "chapter-digest-v1",
        "digest_content_hash": "abc",
    }
    store.save_chapter(
        "n1",
        1,
        "第一章",
        "正文",
        summary=digest["summary"],
        status="final",
        digest=digest,
    )

    chapter = store.get_chapter("n1", 1)

    assert chapter["summary"] == "正文实际摘要"
    assert chapter["digest"] == digest
    assert chapter["events"] == ["主角发现密门"]
    assert chapter["extracted_facts"][0]["subject"] == "密门"


def test_legacy_novel_table_is_migrated_for_planning_review(tmp_path):
    db_path = tmp_path / "legacy-novels.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE novels (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                genre TEXT,
                inspiration TEXT,
                style TEXT,
                total_chapters INTEGER DEFAULT 10,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("INSERT INTO novels (id, title) VALUES ('old', '旧作品')")

    cfg = Config(
        sqlite_db_path=str(db_path),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
    )
    migrated = NovelStore(cfg)

    with sqlite3.connect(migrated.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(novels)")}
    assert "planning_review_enabled" in columns
    assert "creative_brief_json" in columns
    assert "creative_brief_version" in columns
    assert "tenant_id" in columns
    assert "created_by" in columns
    assert migrated.get_novel("old")["planning_review_enabled"] is False
    assert migrated.get_novel("old")["creative_brief"]["age_rating"] == "teen"
    assert migrated.get_novel("old")["tenant_id"] == "tenant_local"


def test_novel_queries_are_tenant_scoped(store):
    from security import Principal, reset_current_principal, set_current_principal

    alice_token = set_current_principal(Principal("user-a", "tenant-a", "alice", "owner"))
    try:
        alice_novel = store.create_novel("alice-novel", "Alice 作品")
    finally:
        reset_current_principal(alice_token)

    bob_token = set_current_principal(Principal("user-b", "tenant-b", "bob", "owner"))
    try:
        store.create_novel("bob-novel", "Bob 作品")
        assert store.list_novels()[0]["id"] == "bob-novel"
        assert store.get_novel(alice_novel["id"]) is None
    finally:
        reset_current_principal(bob_token)


def test_auth_rate_limit_is_shared_across_store_instances(store):
    second_worker = NovelStore(store.config)

    assert store.consume_auth_rate_limit(
        "hashed-login-key", window_seconds=60, max_attempts=2, now_epoch=100
    ) is None
    assert second_worker.consume_auth_rate_limit(
        "hashed-login-key", window_seconds=60, max_attempts=2, now_epoch=101
    ) is None
    assert store.consume_auth_rate_limit(
        "hashed-login-key", window_seconds=60, max_attempts=2, now_epoch=102
    ) == 58
    assert second_worker.consume_auth_rate_limit(
        "hashed-login-key", window_seconds=60, max_attempts=2, now_epoch=160
    ) is None


def test_auth_rate_limit_is_atomic_under_concurrent_workers(store):
    workers = [NovelStore(store.config) for _ in range(8)]

    def consume(worker: NovelStore) -> int | None:
        return worker.consume_auth_rate_limit(
            "concurrent-key", window_seconds=60, max_attempts=3, now_epoch=200
        )

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        results = list(pool.map(consume, workers))

    assert results.count(None) == 3
    assert sum(result is not None for result in results) == 5


def test_creative_brief_updates_append_versions_and_keep_noop_idempotent(store):
    store.create_novel("n1", "书", creative_brief={"themes": ["身份"]})

    updated = store.update_creative_brief(
        "n1",
        {"themes": ["身份", "记忆"], "ending_tone": "open"},
        change_summary="强化主题",
    )
    unchanged = store.update_creative_brief(
        "n1",
        {"themes": ["身份", "记忆"], "ending_tone": "open"},
        change_summary="重复保存",
    )
    reverted = store.update_creative_brief(
        "n1",
        {"themes": ["身份"]},
        change_summary="恢复早期方向",
    )
    versions = store.list_creative_brief_versions("n1")

    assert updated["creative_brief_version"] == 2
    assert unchanged["creative_brief_version"] == 2
    assert reverted["creative_brief_version"] == 3
    assert [item["version_number"] for item in versions] == [3, 2, 1]
    assert versions[1]["change_summary"] == "强化主题"
    assert versions[0]["creative_brief"]["themes"] == ["身份"]


def test_corrupt_creative_brief_does_not_break_novel_reads(store):
    store.create_novel("n1", "书")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE novels SET creative_brief_json = ? WHERE id = ?",
            ("{broken", "n1"),
        )

    novel = store.get_novel("n1")

    assert novel["creative_brief"]["schema_version"] == "creative-brief-v1"
    assert novel["creative_brief"]["target_audience"] == "大众类型小说读者"


def test_corrupt_scene_plan_does_not_break_chapter_reads(store, caplog):
    store.create_novel("n1", "书")
    store.save_chapter("n1", 1, "第一章", "正文")
    store.save_chapter("n1", 2, "第二章", "正文")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE chapters SET scene_plan_json = ? WHERE novel_id = ? AND chapter_number = ?",
            ("{broken", "n1", 1),
        )
        conn.execute(
            "UPDATE chapters SET scene_plan_json = ? WHERE novel_id = ? AND chapter_number = ?",
            ('{"scene_number": 1}', "n1", 2),
        )

    assert store.get_chapter("n1", 1)["scene_plan"] == []
    assert [chapter["scene_plan"] for chapter in store.get_all_chapters("n1")] == [[], []]
    assert "已降级为空列表" in caplog.text


def test_chapter_versions_are_numbered_and_idempotent(store):
    store.create_novel("n1", "书")
    first = store.save_chapter_version(
        "n1",
        1,
        source="initial",
        content="第一稿",
        scene_plan=[{"scene_number": 1}],
        scene_drafts=[{"scene_number": 1, "content": "第一稿"}],
    )
    duplicate = store.save_chapter_version(
        "n1",
        1,
        source="initial",
        content="第一稿",
        scene_plan=[{"scene_number": 1}],
        scene_drafts=[{"scene_number": 1, "content": "第一稿"}],
    )
    second = store.save_chapter_version(
        "n1",
        1,
        source="revision",
        content="第二稿",
    )

    assert first["version_number"] == duplicate["version_number"] == 1
    assert second["version_number"] == 2
    versions = store.list_chapter_versions("n1", 1)
    assert [item["version_number"] for item in versions] == [1, 2]
    assert versions[0]["preview"] == "第一稿"
    assert "content" not in versions[0]
    restored = store.get_chapter_version("n1", 1, 1)
    assert restored["content"] == "第一稿"
    assert restored["scene_drafts"] == [{"scene_number": 1, "content": "第一稿"}]


def test_delete_novel_removes_chapter_versions(store):
    store.create_novel("n1", "书")
    store.save_chapter_version("n1", 1, source="initial", content="第一稿")

    store.delete_novel("n1")

    assert store.list_chapter_versions("n1", 1) == []


def test_planning_versions_are_numbered_scoped_and_idempotent(store):
    store.create_novel("n1", "书")
    generated_payload = {
        "world_bible": "城市: 雾都",
        "characters": [{"name": "林寒"}],
        "outline": [{"chapter": 1, "title": "雾起"}],
    }
    generated = store.save_planning_version(
        "n1",
        "blueprint",
        99,
        source="generated",
        payload=generated_payload,
    )
    duplicate = store.save_planning_version(
        "n1",
        "blueprint",
        0,
        source="generated",
        payload=generated_payload,
    )
    approved = store.save_planning_version(
        "n1",
        "blueprint",
        0,
        source="approved",
        payload={**generated_payload, "world_bible": "城市: 雾都\n规则: 禁止夜行"},
    )
    scene = store.save_planning_version(
        "n1",
        "scene",
        1,
        source="generated",
        payload={"scene_plan": [{"scene_number": 1, "estimated_words": 800}]},
    )

    assert generated["version_number"] == duplicate["version_number"] == 1
    assert approved["version_number"] == 2
    assert scene["version_number"] == 1
    versions = store.list_planning_versions("n1", "blueprint")
    assert [item["source"] for item in versions] == ["generated", "approved"]
    assert versions[0]["preview"] == "世界观 6 字 · 1 角色 · 1 章"
    assert "payload" not in versions[0]
    restored = store.get_planning_version("n1", "blueprint", 0, 2)
    assert "禁止夜行" in restored["payload"]["world_bible"]
    assert store.list_planning_versions("n1", "scene", 1)[0]["preview"] == "1 场 · 800 字"


def test_delete_novel_removes_planning_versions(store):
    store.create_novel("n1", "书")
    store.save_planning_version(
        "n1",
        "blueprint",
        0,
        source="generated",
        payload={"world_bible": "城市: 雾都"},
    )

    store.delete_novel("n1")

    assert store.list_planning_versions("n1", "blueprint") == []


def test_chapter_evaluations_roundtrip_and_single_baseline(store):
    store.create_novel("n1", "书")
    first = store.save_chapter_evaluation(
        "n1",
        1,
        1,
        content_hash="hash-1",
        evaluator_version="rules-v1",
        rubric_version="",
        deterministic_scores={"structure": 80},
        judge_scores=None,
        overall_score=80,
        findings=[{"message": "结构完整"}],
    )
    second = store.save_chapter_evaluation(
        "n1",
        1,
        2,
        content_hash="hash-2",
        evaluator_version="rules-v1",
        rubric_version="judge-v1",
        deterministic_scores={"structure": 90},
        judge_scores={"coherence": 88},
        overall_score=89,
        findings=[],
        model_provider="openai",
        model_name="judge-model",
    )

    baseline = store.set_chapter_evaluation_baseline("n1", 1, first["id"])
    assert baseline["is_baseline"] is True
    store.set_chapter_evaluation_baseline("n1", 1, second["id"])
    evaluations = store.list_chapter_evaluations("n1", 1)

    assert [item["version_number"] for item in evaluations] == [2, 1]
    assert evaluations[0]["judge_scores"] == {"coherence": 88}
    assert evaluations[0]["is_baseline"] is True
    assert evaluations[1]["is_baseline"] is False
    assert store.get_latest_chapter_evaluation("n1", 1, 2)["id"] == second["id"]
    assert store.get_chapter_evaluation_baseline("n1", 1)["id"] == second["id"]


def test_delete_novel_removes_chapter_evaluations(store):
    store.create_novel("n1", "书")
    store.save_chapter_evaluation(
        "n1",
        1,
        1,
        content_hash="hash",
        evaluator_version="rules-v1",
        rubric_version="",
        deterministic_scores={},
        judge_scores={},
        overall_score=0,
        findings=[],
    )

    store.delete_novel("n1")

    assert store.list_chapter_evaluations("n1", 1) == []


def test_evaluation_benchmark_runs_roundtrip(store):
    report = {
        "suite_version": "suite-v1",
        "evaluator_version": "chapter-v1",
        "rubric_version": "judge-v1",
        "prompt_hash": "prompt",
        "input_hash": "input",
        "include_judge": False,
        "model_provider": "",
        "model_name": "",
        "baseline_run_id": None,
        "gate_threshold": 70,
        "regression_threshold": 3,
        "overall_score": 91.2,
        "status": "passed",
        "judge_error": "",
        "cases": [{"id": "sample", "overall_score": 91.2, "passed": True}],
    }
    saved = store.save_evaluation_benchmark(report)
    assert saved["id"].startswith("eval_")
    assert saved["cases"][0]["id"] == "sample"
    assert store.get_evaluation_benchmark(saved["id"])["overall_score"] == 91.2
    assert store.list_evaluation_benchmarks(1)[0]["id"] == saved["id"]


def test_chapter_candidates_roundtrip_selection_and_idempotency(store):
    store.create_novel("n1", "书")
    payload = {
        "generation_id": "job-candidates",
        "candidate_number": 1,
        "source_hash": "source-hash",
        "instruction": "加强人物冲突",
        "title": "雾起",
        "content": "候选正文",
        "summary": "候选摘要",
        "scene_plan": [{"scene_number": 1, "goal": "入城"}],
        "scene_drafts": [{"scene_number": 1, "content": "候选正文"}],
        "scores": {"structure": 90.0},
        "overall_score": 90.0,
        "evaluation_schema_version": "chapter-quality-v1",
    }
    first = store.save_chapter_candidate("n1", 1, **payload)
    duplicate = store.save_chapter_candidate(
        "n1",
        1,
        **{**payload, "content": "不应覆盖"},
    )

    assert first["id"] == duplicate["id"]
    assert duplicate["content"] == "候选正文"
    assert duplicate["scores"] == {"structure": 90.0}
    assert duplicate["scene_drafts"][0]["content"] == "候选正文"
    assert store.get_chapter_candidate("n1", first["id"])["source_hash"] == "source-hash"

    selected = store.mark_chapter_candidate_selected("n1", 1, first["id"])
    assert selected["status"] == "selected"
    assert selected["selected_at"]
    assert store.list_chapter_candidates("n1", 1)[0]["id"] == first["id"]


def test_delete_novel_removes_chapter_candidates(store):
    store.create_novel("n1", "书")
    store.save_chapter_candidate(
        "n1",
        1,
        generation_id="job-candidates",
        candidate_number=1,
        source_hash="source-hash",
        instruction="",
        title="雾起",
        content="候选正文",
    )

    store.delete_novel("n1")

    assert store.list_chapter_candidates("n1", 1) == []


def test_book_audit_is_idempotent_and_deleted_with_novel(store):
    store.create_novel("n1", "书")
    report = {"overall_score": 88, "findings": []}
    first = store.save_book_audit(
        "n1",
        manuscript_hash="manuscript-hash",
        schema_version="book-audit-v1",
        rubric_version="rubric-v1",
        report=report,
    )
    second = store.save_book_audit(
        "n1",
        manuscript_hash="manuscript-hash",
        schema_version="book-audit-v1",
        rubric_version="rubric-v1",
        report={"overall_score": 10},
    )

    assert first["id"] == second["id"]
    assert store.get_latest_book_audit("n1")["report"] == report
    assert len(store.list_book_audits("n1")) == 1

    store.delete_novel("n1")
    assert store.list_book_audits("n1") == []


def test_memory_snapshot_is_idempotent_and_deleted_with_novel(store):
    store.create_novel("n1", "书")
    payload = {
        "schema_version": "book-memory-v1",
        "completed_chapters": 2,
        "arcs": [{"arc": 1}],
    }
    first = store.save_memory_snapshot(
        "n1",
        schema_version="book-memory-v1",
        content_hash="memory-hash",
        payload=payload,
    )
    duplicate = store.save_memory_snapshot(
        "n1",
        schema_version="book-memory-v1",
        content_hash="memory-hash",
        payload={"completed_chapters": 99},
    )

    assert first["id"] == duplicate["id"]
    assert store.get_latest_memory_snapshot("n1")["payload"] == payload
    assert len(store.list_memory_snapshots("n1")) == 1

    store.delete_novel("n1")
    assert store.list_memory_snapshots("n1") == []


def test_run_jobs_persist_events_and_enforce_one_active_job(store):
    store.create_novel("n1", "书")
    job = store.create_run_job("job-1", "n1", "run", {"source": "test"})

    with pytest.raises(ValueError, match="活动任务"):
        store.create_run_job("job-2", "n1", "run")

    started = store.update_run_job(job["id"], status="running", current_node="world_builder")
    first = store.append_run_job_event(job["id"], {"type": "job_started"})
    second = store.append_run_job_event(
        job["id"],
        {"type": "node_done", "node": "world_builder"},
    )

    assert started["status"] == "running"
    assert started["started_at"]
    assert [first["sequence"], second["sequence"]] == [1, 2]
    assert store.list_run_job_events(job["id"], after_sequence=1)[0]["payload"] == {
        "type": "node_done",
        "node": "world_builder",
    }

    completed = store.update_run_job(job["id"], status="completed", current_node="")
    next_job = store.create_run_job("job-2", "n1", "run")
    assert completed["finished_at"]
    assert next_job["status"] == "queued"


def test_run_job_cancel_and_restart_interruption(store):
    store.create_novel("n1", "书")
    first = store.create_run_job("job-1", "n1", "run")
    requested = store.request_run_job_cancel(first["id"])
    assert requested["cancel_requested"] is True
    store.update_run_job(first["id"], status="cancelled", error="用户取消")

    store.create_run_job("job-2", "n1", "run")
    store.update_run_job("job-2", status="running")
    assert store.interrupt_active_run_jobs() == 1
    interrupted = store.get_run_job("job-2")
    assert interrupted["status"] == "interrupted"
    assert "服务重启" in interrupted["error"]


def test_run_job_lease_claim_renew_and_expiry_recovery(store):
    store.create_novel("lease-novel", "租约")
    first = store.create_run_job("lease-1", "lease-novel", "run")

    claimed = store.claim_run_job(first["id"], "worker-a", 60)
    assert claimed["status"] == "running"
    assert claimed["lease_owner"] == "worker-a"
    assert claimed["attempt_count"] == 1
    assert store.claim_run_job(first["id"], "worker-b", 60) is None
    assert store.renew_run_job_lease(first["id"], "worker-a", 60) is True
    assert store.release_run_job_lease(first["id"], "worker-a") is True

    reclaimed = store.claim_run_job(first["id"], "worker-b", 60)
    assert reclaimed["lease_owner"] == "worker-b"
    assert reclaimed["attempt_count"] == 2
    assert store.recover_expired_run_jobs() == 0

    with store._conn() as conn:
        conn.execute(
            "UPDATE run_jobs SET lease_expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00", first["id"]),
        )
    assert store.recover_expired_run_jobs() == 1
    recovered = store.get_run_job(first["id"])
    assert recovered["status"] == "interrupted"
    assert recovered["lease_owner"] is None


def test_run_job_creation_can_reserve_a_lease_before_dispatch(store):
    store.create_novel("reserved-novel", "预留")
    job = store.create_run_job(
        "reserved-1",
        "reserved-novel",
        "run",
        lease_owner="worker-a",
        lease_seconds=60,
    )

    assert job["status"] == "queued"
    assert job["lease_owner"] == "worker-a"
    assert job["attempt_count"] == 1
    assert store.claim_run_job(job["id"], "worker-a", 60)["attempt_count"] == 1
    assert store.claim_run_job(job["id"], "worker-b", 60) is None


def test_run_job_shutdown_only_interrupts_jobs_owned_by_current_worker(store):
    store.create_novel("shutdown-a", "关闭 A")
    store.create_novel("shutdown-b", "关闭 B")
    store.create_run_job(
        "shutdown-job-a",
        "shutdown-a",
        "run",
        lease_owner="worker-a",
        lease_seconds=60,
    )
    store.create_run_job(
        "shutdown-job-b",
        "shutdown-b",
        "run",
        lease_owner="worker-b",
        lease_seconds=60,
    )

    assert store.interrupt_run_jobs_by_owner("worker-a") == 1
    assert store.get_run_job("shutdown-job-a")["status"] == "interrupted"
    assert store.get_run_job("shutdown-job-b")["status"] == "queued"


def test_delete_novel_removes_run_jobs_and_events(store):
    store.create_novel("n1", "书")
    store.create_run_job("job-1", "n1", "run")
    store.append_run_job_event("job-1", {"type": "job_started"})

    store.delete_novel("n1")

    assert store.get_run_job("job-1") is None
    assert store.list_run_job_events("job-1") == []
