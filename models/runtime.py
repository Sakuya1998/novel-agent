"""模型调用治理:上下文、超时重试、故障转移与用量记录。"""

import asyncio
import hashlib
import json
import re
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from config import Config
from models.model_settings import ModelSettingsStore


class ModelBudgetExceededError(RuntimeError):
    """作品累计 token 已达到配置预算。"""


@dataclass(frozen=True)
class ModelCallContext:
    novel_id: str = ""
    agent: str = "unknown"


_CALL_CONTEXT: ContextVar[ModelCallContext | None] = ContextVar(
    "model_call_context",
    default=None,
)


@contextmanager
def model_call_context(novel_id: str, agent: str):
    """为当前异步节点附加作品和 Agent 标识。"""
    token = _CALL_CONTEXT.set(ModelCallContext(novel_id=novel_id, agent=agent))
    try:
        yield
    finally:
        _CALL_CONTEXT.reset(token)


def _estimate_tokens(value: Any) -> int:
    text = str(value or "")
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = max(len(text) - cjk, 0)
    return cjk + max((non_cjk + 3) // 4, 0)


def _trace_text(value: Any) -> str:
    """将模型输入/输出转换为稳定的脱敏摘要源,不持久化原文。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value or "")


def _trace_digest(value: Any) -> tuple[str, int]:
    text = _trace_text(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text)


def _usage_from_response(response: Any, model_input: Any) -> tuple[int, int, bool]:
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is not None and output_tokens is not None:
            return int(input_tokens), int(output_tokens), False

    metadata = getattr(response, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    if isinstance(token_usage, dict):
        input_tokens = token_usage.get("prompt_tokens", token_usage.get("input_tokens"))
        output_tokens = token_usage.get("completion_tokens", token_usage.get("output_tokens"))
        if input_tokens is not None and output_tokens is not None:
            return int(input_tokens), int(output_tokens), False

    content = getattr(response, "content", response)
    return _estimate_tokens(model_input), _estimate_tokens(content), True


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    message = str(exc).lower()
    return any(token in message for token in (
        "timeout",
        "timed out",
        "429",
        "rate limit",
        "too many requests",
        "500",
        "502",
        "503",
        "504",
        "temporarily unavailable",
        "connection reset",
    ))


class ManagedChatModel:
    """为一个主模型和可选备用模型提供统一的 ``ainvoke``。"""

    def __init__(
        self,
        candidates: list[tuple[Any, Any]],
        *,
        purpose: str,
        config: Config,
        store: ModelSettingsStore,
    ):
        self.candidates = candidates
        self.purpose = purpose
        self.config = config
        self.store = store

    async def ainvoke(self, model_input: Any, config: Any = None, **kwargs: Any) -> Any:
        context = _CALL_CONTEXT.get() or ModelCallContext()
        call_id = uuid4().hex
        input_hash, input_chars = _trace_digest(model_input)
        if context.novel_id and self.config.max_novel_tokens > 0:
            usage = self.store.get_model_usage(context.novel_id)
            if int(usage["total_tokens"]) >= self.config.max_novel_tokens:
                raise ModelBudgetExceededError(
                    f"作品 token 预算已用尽({usage['total_tokens']}/{self.config.max_novel_tokens})"
                )

        last_error: Exception | None = None
        attempts_per_model = max(int(self.config.model_retry_attempts), 1)
        for candidate_index, (resolved, model) in enumerate(self.candidates):
            for attempt in range(1, attempts_per_model + 1):
                started = perf_counter()
                try:
                    call = model.ainvoke(model_input, config=config, **kwargs)
                    if self.config.model_timeout_seconds > 0:
                        response = await asyncio.wait_for(
                            call,
                            timeout=self.config.model_timeout_seconds,
                        )
                    else:
                        response = await call
                    input_tokens, output_tokens, estimated = _usage_from_response(
                        response,
                        model_input,
                    )
                    output_hash, output_chars = _trace_digest(
                        getattr(response, "content", response)
                    )
                    self._record(
                        resolved,
                        context,
                        attempt,
                        candidate_index > 0,
                        True,
                        perf_counter() - started,
                        input_tokens,
                        output_tokens,
                        estimated,
                        call_id=call_id,
                        input_hash=input_hash,
                        output_hash=output_hash,
                        input_chars=input_chars,
                        output_chars=output_chars,
                    )
                    return response
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = exc
                    self._record(
                        resolved,
                        context,
                        attempt,
                        candidate_index > 0,
                        False,
                        perf_counter() - started,
                        _estimate_tokens(model_input),
                        0,
                        True,
                        error_type=type(exc).__name__,
                        call_id=call_id,
                        input_hash=input_hash,
                        input_chars=input_chars,
                    )
                    if not _retryable(exc) or attempt >= attempts_per_model:
                        break
                    delay = max(float(self.config.model_retry_base_delay), 0) * (2 ** (attempt - 1))
                    if delay:
                        await asyncio.sleep(delay)

        if last_error is None:
            raise RuntimeError("没有可用的聊天模型")
        raise last_error

    def _record(
        self,
        resolved: Any,
        context: ModelCallContext,
        attempt: int,
        fallback_used: bool,
        success: bool,
        duration_seconds: float,
        input_tokens: int,
        output_tokens: int,
        usage_estimated: bool,
        error_type: str = "",
        call_id: str = "",
        input_hash: str = "",
        output_hash: str = "",
        input_chars: int = 0,
        output_chars: int = 0,
    ) -> None:
        with suppress(Exception):
            self.store.record_model_call(
                novel_id=context.novel_id,
                agent=context.agent,
                purpose=self.purpose,
                provider=resolved.provider,
                model_name=resolved.model_name,
                attempt=attempt,
                fallback_used=fallback_used,
                success=success,
                duration_ms=round(duration_seconds * 1000),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usage_estimated=usage_estimated,
                error_type=error_type,
                call_id=call_id,
                trace_id=uuid4().hex,
                input_hash=input_hash,
                output_hash=output_hash,
                input_chars=input_chars,
                output_chars=output_chars,
            )
