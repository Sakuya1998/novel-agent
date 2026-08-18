"""模型超时重试、故障转移、预算和用量统计测试。"""

from types import SimpleNamespace

import pytest

from config import Config
from models.model_settings import ModelSettingsStore
from models.runtime import (
    ManagedChatModel,
    ModelBudgetExceededError,
    model_call_context,
)


class SequenceModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def ainvoke(self, model_input, config=None, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _resolved(name: str):
    return SimpleNamespace(provider="openai", model_name=name)


def _runtime(tmp_path, **overrides):
    cfg = Config(
        sqlite_db_path=str(tmp_path / "runtime.db"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        model_secret_key_path=str(tmp_path / "model-settings.key"),
        model_retry_base_delay=0,
        **overrides,
    )
    return cfg, ModelSettingsStore(cfg)


async def test_transient_failure_retries_and_records_usage(tmp_path):
    cfg, store = _runtime(tmp_path, model_retry_attempts=2)
    response = SimpleNamespace(
        content="完成",
        usage_metadata={"input_tokens": 5, "output_tokens": 7},
        response_metadata={},
    )
    primary = SequenceModel([TimeoutError("timed out"), response])
    model = ManagedChatModel(
        [(_resolved("primary"), primary)],
        purpose="creative",
        config=cfg,
        store=store,
    )

    with model_call_context("novel_1", "scene_writer"):
        result = await model.ainvoke("写一章")

    usage = store.get_model_usage("novel_1")
    assert result.content == "完成"
    assert primary.calls == 2
    assert usage["attempts"] == 2
    assert usage["failed_attempts"] == 1
    assert usage["successful_calls"] == 1
    assert usage["output_tokens"] == 7
    assert usage["by_agent"][0]["agent"] == "scene_writer"
    traces = store.list_model_traces("novel_1")
    assert len(traces) == 2
    assert traces[0]["call_id"] == traces[1]["call_id"]
    assert traces[0]["trace_id"] != traces[1]["trace_id"]
    assert traces[0]["input_hash"]
    assert traces[0]["input_chars"] > 0
    assert traces[0]["output_hash"]
    assert "完成" not in traces[0]


async def test_primary_failure_uses_configured_fallback(tmp_path):
    cfg, store = _runtime(tmp_path, model_retry_attempts=1)
    primary = SequenceModel([RuntimeError("503 temporarily unavailable")])
    fallback = SequenceModel([SimpleNamespace(content="备用成功", usage_metadata=None, response_metadata={})])
    model = ManagedChatModel(
        [(_resolved("primary"), primary), (_resolved("fallback"), fallback)],
        purpose="analysis",
        config=cfg,
        store=store,
    )

    with model_call_context("novel_1", "consistency_checker"):
        result = await model.ainvoke("检查")

    usage = store.get_model_usage("novel_1")
    assert result.content == "备用成功"
    assert primary.calls == fallback.calls == 1
    assert usage["fallback_attempts"] == 1
    assert usage["failed_attempts"] == 1


async def test_token_budget_stops_before_calling_provider(tmp_path):
    cfg, store = _runtime(tmp_path, model_retry_attempts=1, max_novel_tokens=10)
    store.record_model_call(
        novel_id="novel_1",
        agent="scene_writer",
        purpose="creative",
        provider="openai",
        model_name="primary",
        attempt=1,
        fallback_used=False,
        success=True,
        duration_ms=1,
        input_tokens=4,
        output_tokens=6,
        usage_estimated=False,
    )
    primary = SequenceModel([SimpleNamespace(content="不应调用")])
    model = ManagedChatModel(
        [(_resolved("primary"), primary)],
        purpose="creative",
        config=cfg,
        store=store,
    )

    with model_call_context("novel_1", "scene_writer"), pytest.raises(
        ModelBudgetExceededError,
        match="预算已用尽",
    ):
        await model.ainvoke("继续")

    assert primary.calls == 0
