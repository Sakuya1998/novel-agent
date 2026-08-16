"""LLM 接入层:统一封装 OpenAI 兼容 API 与 Anthropic API 的流式调用。"""
import asyncio
from typing import AsyncIterator, Optional


class LLMError(Exception):
    """LLM 调用失败(配置缺失、鉴权错误、网络错误等)。"""


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str = "", base_url: str = ""):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def _require(self):
        if self.provider == "mock":
            return
        if not self.model:
            raise LLMError("未配置模型名,请在「设置」中填写 model。")
        if not self.api_key:
            raise LLMError(
                f"未配置 {self.provider} 的 API Key,请在「设置」中填写,或设置对应环境变量。"
            )

    async def stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.8,
        max_tokens: Optional[int] = None,
        mock_text: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """流式生成,yield 文本增量。mock_text 仅在 mock provider 下使用。"""
        self._require()
        if self.provider == "mock":
            async for chunk in self._mock_stream(mock_text or "(模拟输出)这是一段离线演示文本。"):
                yield chunk
            return
        try:
            if self.provider == "anthropic":
                async for chunk in self._stream_anthropic(system, user, temperature, max_tokens):
                    yield chunk
            else:
                async for chunk in self._stream_openai(system, user, temperature, max_tokens):
                    yield chunk
        except LLMError:
            raise
        except Exception as e:  # SDK 各类异常统一转译
            raise LLMError(f"调用模型失败:{e}") from e

    async def _stream_openai(self, system, user, temperature, max_tokens) -> AsyncIterator[str]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
        )
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
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url or None,
        )
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
