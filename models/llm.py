"""统一的 LLM 模型管理(文档 7.4)。

根据 config.llm_provider 返回对应的 LangChain Chat 模型实例。
支持 OpenAI 与 Anthropic 两种 Provider。
"""

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from config import Config


@lru_cache(maxsize=4)
def get_llm(
    temperature: float | None = None,
    model_name: str | None = None,
    streaming: bool = True,
) -> BaseChatModel:
    """获取 LLM 实例(按 provider+model+temperature 缓存复用连接池)。

    Args:
        temperature: 覆盖配置温度(创作类节点用高值,分析类用低值)
        model_name: 覆盖配置模型名
        streaming: 是否启用流式输出(默认 True,配合 LangGraph astream_events)

    Returns:
        LangChain BaseChatModel 实例
    """
    cfg = Config()
    provider = cfg.llm_provider.lower()
    model = model_name or cfg.model_name
    temp = cfg.temperature if temperature is None else temperature

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(  # type: ignore[call-arg]
            model=model,
            temperature=temp,
            max_tokens=cfg.max_tokens,
            anthropic_api_key=cfg.anthropic_api_key,
            streaming=streaming,
        )

    # 默认 OpenAI 兼容通道
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(  # type: ignore[call-arg]
        model=model,
        temperature=temp,
        max_tokens=cfg.max_tokens,
        api_key=cfg.openai_api_key,
        streaming=streaming,
    )


def get_analyzer_llm() -> BaseChatModel:
    """分析类节点专用:低温度保证输出稳定(一致性检查/情节规划)。"""
    return get_llm(temperature=0.3)
