"""将全局模型路由解析为 LangChain 聊天与嵌入客户端。"""

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from time import perf_counter
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config import Config
from models.model_settings import (
    ModelProfileNotFoundError,
    ModelSettingsStore,
    ProviderName,
    RoutePurpose,
)


class ModelConfigurationError(RuntimeError):
    """缺少可运行的模型路由或 API Key。"""


class ModelConnectionError(RuntimeError):
    """模型服务连接测试失败，消息已脱敏。"""


@dataclass(frozen=True)
class ResolvedModel:
    purpose: RoutePurpose
    provider: ProviderName
    model_name: str
    base_url: str
    api_key: str
    max_tokens: int
    source: Literal["database", "environment"]


@lru_cache(maxsize=32)
def _build_openai_chat(
    resolved: ResolvedModel,
    temperature: float,
    streaming: bool,
) -> BaseChatModel:
    kwargs = {
        "model": resolved.model_name,
        "temperature": temperature,
        "max_tokens": resolved.max_tokens,
        "api_key": resolved.api_key,
        "streaming": streaming,
    }
    if resolved.base_url:
        kwargs["base_url"] = resolved.base_url
    return ChatOpenAI(**kwargs)  # type: ignore[arg-type]


@lru_cache(maxsize=32)
def _build_anthropic_chat(
    resolved: ResolvedModel,
    temperature: float,
    streaming: bool,
) -> BaseChatModel:
    return ChatAnthropic(  # type: ignore[call-arg]
        model=resolved.model_name,
        temperature=temperature,
        max_tokens=resolved.max_tokens,
        anthropic_api_key=resolved.api_key,
        streaming=streaming,
    )


@lru_cache(maxsize=16)
def _build_embeddings(resolved: ResolvedModel) -> Embeddings:
    kwargs = {"model": resolved.model_name, "api_key": resolved.api_key}
    if resolved.base_url:
        kwargs["base_url"] = resolved.base_url
    return OpenAIEmbeddings(**kwargs)  # type: ignore[arg-type]


def sanitize_provider_error(exc: Exception, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Return a diagnostic that cannot echo configured credentials or provider payloads."""
    message = str(exc)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    message = re.sub(r"(?i)(authorization[:=]\s*bearer\s+)[^\s,;]+", r"\1***", message)
    message = re.sub(r"(?i)(api[_-]?key[=:]\s*)[^\s,;&]+", r"\1***", message)
    message = re.sub(r"([?&](?:key|token|api_key)=)[^&\s]+", r"\1***", message)
    lowered = message.lower()
    if any(token in lowered for token in ("401", "403", "unauthorized", "authentication")):
        return "认证失败，请检查 API Key"
    if "timeout" in lowered or "timed out" in lowered:
        return "连接超时，请检查 API 地址和网络"
    if type(exc).__name__ in {"ModelConfigurationError", "StructuredOutputError"}:
        return message[:300]
    return f"模型服务调用失败 ({type(exc).__name__})"


class ModelResolver:
    """按用途读取最新模型路由，并构造对应协议客户端。"""

    def __init__(
        self,
        config: Config | None = None,
        store: ModelSettingsStore | None = None,
    ):
        self.config = config or Config()
        self.store = store or ModelSettingsStore(self.config)

    def resolve(self, purpose: RoutePurpose) -> ResolvedModel:
        routes = self.store.get_routes()
        target = routes.get(purpose)
        if target is not None:
            try:
                profile = self.store.get_runtime_profile(target["profile_id"])
            except ModelProfileNotFoundError as exc:
                raise ModelConfigurationError(f"{purpose} 路由引用的模型服务不存在") from exc
            api_key = str(profile["api_key"])
            if not api_key:
                raise ModelConfigurationError(f"{purpose} 模型服务尚未配置 API Key")
            return ResolvedModel(
                purpose=purpose,
                provider=profile["provider"],
                model_name=target["model_name"],
                base_url=profile["base_url"],
                api_key=api_key,
                max_tokens=self.config.max_tokens,
                source="database",
            )

        if routes:
            raise ModelConfigurationError(f"尚未配置完整的 {purpose} 模型路由")
        return self._resolve_environment(purpose)

    def _resolve_environment(self, purpose: RoutePurpose) -> ResolvedModel:
        if purpose == "embedding":
            provider: ProviderName = "openai"
            model_name = self.config.embedding_model
            api_key = self.config.openai_api_key
        else:
            provider = self.config.llm_provider
            model_name = self.config.model_name
            api_key = (
                self.config.anthropic_api_key
                if provider == "anthropic"
                else self.config.openai_api_key
            )
        if not api_key:
            label = {"creative": "创作", "analysis": "分析", "embedding": "嵌入"}[purpose]
            raise ModelConfigurationError(f"{label}模型尚未配置 API Key，请在工作台模型设置中完成配置")
        return ResolvedModel(
            purpose=purpose,
            provider=provider,
            model_name=model_name,
            base_url="",
            api_key=api_key,
            max_tokens=self.config.max_tokens,
            source="environment",
        )

    def validate_runtime(self) -> None:
        for purpose in ("creative", "analysis", "embedding"):
            resolved = self.resolve(purpose)  # type: ignore[arg-type]
            if purpose == "embedding" and resolved.provider == "anthropic":
                raise ModelConfigurationError("Anthropic 服务不能用于嵌入模型")

    def chat(
        self,
        purpose: Literal["creative", "analysis"],
        temperature: float | None = None,
        model_name: str | None = None,
        streaming: bool = True,
    ) -> BaseChatModel:
        resolved = self.resolve(purpose)
        if model_name:
            resolved = replace(resolved, model_name=model_name)
        selected_temperature = self.config.temperature if temperature is None else temperature
        if resolved.provider == "anthropic":
            return _build_anthropic_chat(resolved, selected_temperature, streaming)
        return _build_openai_chat(resolved, selected_temperature, streaming)

    def embeddings(self) -> Embeddings:
        resolved = self.resolve("embedding")
        if resolved.provider == "anthropic":
            raise ModelConfigurationError("Anthropic 服务不能用于嵌入模型")
        return _build_embeddings(resolved)

    async def test_profile(
        self,
        profile_id: str,
        kind: Literal["chat", "embedding"],
        model_name: str,
    ) -> dict[str, object]:
        profile = self.store.get_runtime_profile(profile_id)
        secret = str(profile["api_key"])
        if not secret:
            raise ModelConnectionError("模型服务尚未配置 API Key")
        purpose: RoutePurpose = "embedding" if kind == "embedding" else "creative"
        resolved = ResolvedModel(
            purpose=purpose,
            provider=profile["provider"],
            model_name=model_name.strip(),
            base_url=profile["base_url"],
            api_key=secret,
            max_tokens=min(self.config.max_tokens, 32),
            source="database",
        )
        if not resolved.model_name:
            raise ModelConnectionError("测试模型名称不能为空")

        started = perf_counter()
        try:
            if kind == "embedding":
                if resolved.provider == "anthropic":
                    raise ModelConnectionError("Anthropic 服务不能用于嵌入模型")
                await _build_embeddings(resolved).aembed_query("connection test")
            else:
                if resolved.provider == "anthropic":
                    model = _build_anthropic_chat(resolved, 0.0, False)
                else:
                    model = _build_openai_chat(resolved, 0.0, False)
                await model.ainvoke("只回复 OK")
        except ModelConnectionError:
            raise
        except Exception as exc:
            raise ModelConnectionError(sanitize_provider_error(exc, [secret])) from None
        return {
            "ok": True,
            "latency_ms": round((perf_counter() - started) * 1000),
            "message": "连接成功",
        }
