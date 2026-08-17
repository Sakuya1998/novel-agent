"""Streamlit 异步 LangGraph 运行时测试。"""


def test_streamlit_runtime_opens_persistent_graph_and_closes(tmp_path):
    from ui.runtime import StreamlitGraphRuntime

    runtime = StreamlitGraphRuntime(str(tmp_path / "checkpoints.db"))
    try:
        snapshot = runtime.get_state("missing-thread")
        assert snapshot.values == {}
    finally:
        runtime.close()
