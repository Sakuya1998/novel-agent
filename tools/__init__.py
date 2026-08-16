"""工具包:全部 Agent 可用工具的注册入口(文档 6.2)。

注:文档 6.2 的 initialize_agent 属于 LangChain 0.x 旧 Agent 体系,
在 LangChain 1.x 已移除;此处等价改用 langgraph.prebuilt.create_react_agent
(工具调用语义不变:LLM 决定何时调用工具并整合结果)。
"""

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import create_react_agent

from tools.analysis_tools import analyze_pacing, calculate_timeline, check_character_behavior
from tools.export_tools import export_to_format
from tools.search_tools import search_inspiration

# 全部工具(供 LangGraph 节点按需绑定)
ALL_TOOLS: list[BaseTool] = [
    search_inspiration,
    calculate_timeline,
    check_character_behavior,
    analyze_pacing,
    export_to_format,
]

__all__ = [
    "ALL_TOOLS",
    "search_inspiration",
    "calculate_timeline",
    "check_character_behavior",
    "analyze_pacing",
    "export_to_format",
    "create_tool_agent",
    "tool",
]


def create_tool_agent(llm, tools: list[BaseTool] | None = None, verbose: bool = True):
    """创建可调用工具的 ReAct Agent。

    Args:
        llm: LangChain Chat 模型(需支持 tool calling)
        tools: 工具列表,默认 ALL_TOOLS
        verbose: 兼容参数(1.x 事件流由调用方自行订阅)

    Returns:
        CompiledStateGraph,invoke({"messages": [("human", task)]}) 执行
    """
    _ = verbose
    return create_react_agent(llm, tools or ALL_TOOLS)
