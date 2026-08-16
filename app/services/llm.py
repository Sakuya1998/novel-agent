"""LLM 接入层:统一封装 OpenAI 兼容 API 与 Anthropic API 的流式调用。

生产增强:
- 超时与 SDK 内部重试(连接类失败自动重试,流开始后不重试);
- 全局并发信号量,防止过量并发生成打爆上游配额;
- 客户端实例按配置指纹缓存复用(连接池),配置变更自动重建;
- 进程退出时统一关闭(async close)。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

logger = logging.getLogger("novel.llm")

# 进程内调用统计。
#
# 线程模型(无锁的正确性依据,修改前请阅读):
# - 所有写入(stream() 内的 +=/-=)都位于事件循环单线程,且 `+=` 字节码段内无 await 点,
#   协程不会互相打断 —— 写-写竞态不存在;
# - 读取方必须与写入方同线程:async 路由(routes_health.stats)在事件循环内读,
#   禁止把本 dict 传入 sync 路由/线程池回调中写(那才是竞态的来源);
# - 因此不加 asyncio.Lock:锁无保护作用,反而在多事件循环(如 pytest)下绑定错误的循环。
# 并发正确性由 tests/test_concurrency_stats.py 压力断言守护。
stats = {"streams_total": 0, "streams_active": 0, "errors_total": 0}


class LLMError(Exception):
    """LLM 调用失败(配置缺失、鉴权错误、网络错误、超时等)。"""


@dataclass(frozen=True)
class LLMOptions:
    """LLM 调用治理参数,来自部署配置。"""

    timeout: float = 300.0
    max_retries: int = 2
    concurrency: int = 4


# ---------------- 客户端缓存(按配置指纹) ----------------
_clients: dict[tuple, object] = {}
_semaphore: asyncio.Semaphore | None = None


def _fingerprint(provider: str, model: str, api_key: str, base_url: str, opts: LLMOptions) -> tuple:
    return (provider, model, api_key, base_url, opts.timeout, opts.max_retries)


def _get_client(provider: str, model: str, api_key: str, base_url: str, opts: LLMOptions):
    """按配置指纹获取(或创建)SDK 客户端,复用连接池。

    无 await 点,事件循环内原子,无需加锁(也避免了多事件循环下锁绑定问题)。
    """
    key = _fingerprint(provider, model, api_key, base_url, opts)
    if key in _clients:
        return _clients[key]
    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(
            api_key=api_key or None,
            base_url=base_url or None,
            timeout=opts.timeout,
            max_retries=opts.max_retries,
        )
    else:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key or None,
            base_url=base_url or None,
            timeout=opts.timeout,
            max_retries=opts.max_retries,
        )
    _clients[key] = client
    return client


async def close_all_clients() -> None:
    """进程退出时关闭全部客户端(优雅关闭)。"""
    for client in _clients.values():
        close = getattr(client, "close", None)
        if close is not None:
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 — 关闭失败不影响退出
                logger.warning("关闭 LLM 客户端失败", exc_info=True)
    _clients.clear()


class LLMClient:
    """面向业务的流式调用入口。"""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str = "",
        base_url: str = "",
        options: LLMOptions | None = None,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.options = options or LLMOptions()

    def _require(self) -> None:
        if self.provider == "mock":
            return
        if not self.model:
            raise LLMError("未配置模型名,请在「设置」中填写 model。")
        if not self.api_key:
            raise LLMError(f"未配置 {self.provider} 的 API Key,请在「设置」中填写,或设置对应环境变量。")

    async def stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        mock_text: str | None = None,
    ) -> AsyncIterator[str]:
        """流式生成,yield 文本增量。mock_text 仅在 mock provider 下使用。"""
        self._require()

        global _semaphore
        stats["streams_total"] += 1
        stats["streams_active"] += 1
        started = time.monotonic()
        try:
            if self.provider == "mock":
                async for chunk in self._mock_stream(mock_text or "(模拟输出)这是一段离线演示文本。"):
                    yield chunk
                return

            if _semaphore is None:
                _semaphore = asyncio.Semaphore(self.options.concurrency)
            semaphore = _semaphore

            async with semaphore:
                try:
                    if self.provider == "anthropic":
                        async for chunk in self._stream_anthropic(system, user, temperature, max_tokens):
                            yield chunk
                    else:
                        async for chunk in self._stream_openai(system, user, temperature, max_tokens):
                            yield chunk
                except LLMError:
                    stats["errors_total"] += 1
                    raise
                except Exception as e:  # SDK 各类异常统一转译
                    stats["errors_total"] += 1
                    raise LLMError(f"调用模型失败:{e}") from e
        finally:
            stats["streams_active"] -= 1
            logger.info(
                "LLM 调用结束 provider=%s model=%s duration=%.1fs",
                self.provider,
                self.model,
                time.monotonic() - started,
            )

    async def _stream_openai(self, system, user, temperature, max_tokens) -> AsyncIterator[str]:
        client = _get_client(self.provider, self.model, self.api_key, self.base_url, self.options)
        kwargs = {}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        stream = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def _stream_anthropic(self, system, user, temperature, max_tokens) -> AsyncIterator[str]:
        client = _get_client(self.provider, self.model, self.api_key, self.base_url, self.options)
        async with client.messages.stream(
            model=self.model,
            system=system,
            max_tokens=max_tokens or 8192,
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    @staticmethod
    async def _mock_stream(text: str) -> AsyncIterator[str]:
        step = 8
        for i in range(0, len(text), step):
            yield text[i : i + step]
            await asyncio.sleep(0.01)
