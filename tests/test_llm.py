"""LLM 客户端测试:mock 流、配置缺失报错、治理参数。"""

import pytest

from app.services.llm import LLMClient, LLMError, LLMOptions


async def test_mock_stream_yields_full_text():
    client = LLMClient(provider="mock", model="mock")
    chunks = [c async for c in client.stream("sys", "user", mock_text="你好,世界")]
    assert "".join(chunks) == "你好,世界"


async def test_mock_stream_without_mock_text():
    client = LLMClient(provider="mock", model="mock")
    chunks = [c async for c in client.stream("sys", "user")]
    assert "".join(chunks)  # 有默认演示文本


async def test_missing_model_raises():
    client = LLMClient(provider="openai", model="", api_key="sk-x")
    with pytest.raises(LLMError, match="模型名"):
        async for _ in client.stream("s", "u"):
            pass


async def test_missing_api_key_raises():
    client = LLMClient(provider="openai", model="gpt-4o-mini", api_key="")
    with pytest.raises(LLMError, match="API Key"):
        async for _ in client.stream("s", "u"):
            pass


async def test_mock_needs_no_credentials():
    client = LLMClient(provider="mock", model="")
    chunks = [c async for c in client.stream("s", "u", mock_text="ok")]
    assert chunks


def test_llm_options_defaults():
    opts = LLMOptions()
    assert opts.timeout == 300.0
    assert opts.max_retries == 2
    assert opts.concurrency == 4
