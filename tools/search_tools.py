"""搜索工具:利用向量记忆进行灵感关联(文档 6.1)。"""

from langchain_core.tools import tool

from memory.vector_store import NovelMemory


@tool
def search_inspiration(query: str, novel_id: str = "", k: int = 3) -> str:
    """根据查询在已有创作记忆中进行语义检索,寻找相关的灵感片段。

    Args:
        query: 检索查询(如"武侠 成长 复仇")
        novel_id: 可选,限定在某部小说的记忆内检索;留空则返回提示
        k: 返回条数

    Returns:
        相关记忆片段文本(供 WorldBuilder 关联灵感)
    """
    if not novel_id:
        return "未指定 novel_id,跳过灵感检索。"

    memory = NovelMemory(novel_id)
    hits = memory.search_similar(query, k=k)
    if not hits:
        return "记忆库中暂无相关内容。"

    lines = ["相关灵感片段:"]
    lines += [f"- {h['content'][:200]}(相关度 {h['distance']:.2f})" for h in hits]
    return "\n".join(lines)
