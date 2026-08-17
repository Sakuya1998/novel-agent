"""Streamlit 使用的持久化异步 LangGraph 同步适配层。"""

import asyncio
import atexit
import threading
from collections.abc import Callable

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from graph.builder import build_graph


class StreamlitGraphRuntime:
    """在固定事件循环上运行异步节点,供 Streamlit 同步回调调用。"""

    def __init__(self, checkpoint_db_path: str):
        self._loop = asyncio.new_event_loop()
        self._lock = threading.RLock()
        self._closed = False
        self._context = AsyncSqliteSaver.from_conn_string(checkpoint_db_path)
        self._checkpointer = self._loop.run_until_complete(self._context.__aenter__())
        self.graph = build_graph(checkpointer=self._checkpointer)
        atexit.register(self.close)

    def _run(self, awaitable):
        with self._lock:
            if self._closed:
                raise RuntimeError("StreamlitGraphRuntime 已关闭")
            return self._loop.run_until_complete(awaitable)

    def get_state(self, novel_id: str):
        graph_config = {"configurable": {"thread_id": novel_id}}
        return self._run(self.graph.aget_state(graph_config))

    def stream(
        self,
        novel_id: str,
        payload: object,
        on_node: Callable[[str], None] | None = None,
    ) -> list[str]:
        graph_config = {"configurable": {"thread_id": novel_id}}

        async def _drive() -> list[str]:
            visited: list[str] = []
            async for update in self.graph.astream(payload, graph_config, stream_mode="updates"):
                for node in (update or {}):
                    if node.startswith("__"):
                        continue
                    visited.append(node)
                    if on_node:
                        on_node(node)
            return visited

        return self._run(_drive())

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._loop.run_until_complete(self._context.__aexit__(None, None, None))
            self._loop.close()
            self._closed = True
