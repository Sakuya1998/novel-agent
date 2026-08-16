"""Streamlit 人机协作界面(文档 9.2 补全实现)。

运行:streamlit run ui/streamlit_app.py

交互模型:
    1. 侧栏填写创作参数 → 「开始创作」同步 stream 驱动图,状态栏实时展示节点进度
    2. 图在 human_review 暂停(interrupt)→ 主区展示章节全文 + 审查输入框
    3. 「通过」或提交修改意见 → Command(resume=...) 续跑,循环直至 END
"""

import asyncio
from uuid import uuid4

import streamlit as st
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from config import STYLE_PROFILES, Config
from graph.builder import build_graph
from memory.sql_store import NovelStore

st.set_page_config(page_title="AI 小说创作工作台", page_icon="📖", layout="wide")

# 同步 API(graph.stream)贴合 Streamlit 同步运行模型,事件循环仅用于驱动
_LOOP = asyncio.new_event_loop()


@st.cache_resource
def get_store() -> NovelStore:
    cfg = Config()
    cfg.ensure_dirs()
    return NovelStore(cfg)


def ensure_graph(novel_id: str):
    """每部小说一个带 MemorySaver 的图实例(缓存于 session_state)。"""
    graphs = st.session_state.setdefault("graphs", {})
    if novel_id not in graphs:
        graphs[novel_id] = build_graph(checkpointer=MemorySaver())
    return graphs[novel_id]


def drive_graph(novel_id: str, payload: object, status_box) -> list[str]:
    """同步迭代图更新,返回本段执行过的节点名列表。"""
    graph = ensure_graph(novel_id)
    config = {"configurable": {"thread_id": novel_id}}
    visited: list[str] = []
    try:
        for update in graph.stream(payload, config, stream_mode="updates"):
            for node, _ in (update or {}).items():
                if node.startswith("__"):
                    continue
                visited.append(node)
                status_box.write(f"✅ {node} 完成")
    except Exception as exc:
        status_box.error(f"执行出错:{exc}")
    return visited


def pending_review(novel_id: str) -> bool:
    """判断图是否暂停在 human_review。"""
    graph = ensure_graph(novel_id)
    snap = graph.get_state({"configurable": {"thread_id": novel_id}})
    return bool(snap.next) and "human_review" in snap.next


def render_review(novel_id: str):
    """人工审查面板:章节全文 + 通过/修改意见。"""
    graph = ensure_graph(novel_id)
    snap = graph.get_state({"configurable": {"thread_id": novel_id}})
    info = {}
    for task in getattr(snap, "tasks", ()):
        if hasattr(task, "interrupts") and task.interrupts:
            info = task.interrupts[0].value or {}
            break

    if not info:  # 兜底:从状态快照取当前草稿
        info = {
            "chapter_number": snap.values.get("current_chapter"),
            "title": (snap.values.get("current_draft") or {}).get("title", ""),
            "content": (snap.values.get("current_draft") or {}).get("content", ""),
        }

    st.subheader(f"📝 第 {info.get('chapter_number', '?')} 章 {info.get('title', '')} — 待审查")
    if info.get("issues"):
        with st.expander("⚠️ 一致性检查发现的问题", expanded=True):
            for i in info["issues"]:
                st.markdown(f"- **[{i.get('severity')}]** {i.get('description')}")
    st.markdown(str(info.get("content", ""))[:5000])

    feedback = st.text_area("修改意见(留空表示通过)", key=f"fb_{novel_id}")
    col1, _ = st.columns([1, 3])
    if col1.button("提交审查", type="primary", key=f"submit_{novel_id}"):
        resume = feedback.strip() or "approve"
        with st.status("续跑创作流水线...") as status:
            drive_graph(novel_id, Command(resume=resume), status)
            status.update(label="本段完成")
        st.rerun()


# ---------------------------------------------------------------------
# 页面布局
# ---------------------------------------------------------------------
st.title("📖 AI 小说创作工作台")
st.caption("Multi-Agent 协作:世界观 → 角色 → 大纲 → 逐章写作 → 风格润色 → 一致性检查 → 人工审查")

with st.sidebar:
    st.header("创作参数")
    title = st.text_input("小说标题", value="雾中剑")
    genre = st.selectbox("类型", ["武侠", "仙侠", "科幻", "悬疑", "都市", "历史"])
    inspiration = st.text_area("一句话灵感", value="一个失忆的剑客在雾都寻找自己的过去,却发现每个人都在说谎。")
    total = st.number_input("总章节数", 1, 50, 3)
    style = st.selectbox("风格", sorted(STYLE_PROFILES), format_func=lambda k: STYLE_PROFILES[k]["name"])

    if st.button("🚀 开始创作", type="primary", use_container_width=True):
        novel_id = f"novel_{uuid4().hex[:8]}"
        st.session_state["novel_id"] = novel_id
        get_store().create_novel(novel_id, title, genre, style, int(total), inspiration)
        st.session_state.pop("finished", None)
        with st.status("创作流水线启动...") as status:
            initial_state = {
                "title": title,
                "genre": genre,
                "inspiration": inspiration,
                "total_chapters": int(total),
                "style": style,
                "novel_id": novel_id,
                "current_chapter": 1,
                "current_phase": "writing",
                "max_revision_attempts": 2,
                "chapters": [],
            }
            drive_graph(novel_id, initial_state, status)
            status.update(label="流水线进入暂停点或完成")
        st.rerun()

    novels = get_store().list_novels()
    if novels:
        st.divider()
        st.header("历史作品")
        for n in novels:
            if st.button(f"{n['title']}({n['total_chapters']}章)", key=f"load_{n['id']}", use_container_width=True):
                st.session_state["novel_id"] = n["id"]
                st.rerun()

# 主区
novel_id = st.session_state.get("novel_id")
if not novel_id:
    st.info("👈 在侧栏填写创作参数,点击「开始创作」")
    st.stop()

if pending_review(novel_id):
    render_review(novel_id)
    st.stop()

# 展示已完成章节(SQLite 定稿记录)
store = get_store()
chapters = store.get_all_chapters(novel_id)
if chapters:
    st.header(f"📚 已定稿章节({len(chapters)} 章)")
    for ch in chapters:
        with st.expander(f"第{ch['chapter_number']}章 {ch['title'] or ''}({ch['word_count'] or 0}字)"):
            st.markdown(ch["content"] or "")
else:
    graph = ensure_graph(novel_id)
    snap = graph.get_state({"configurable": {"thread_id": novel_id}})
    if not snap.next and snap.values:
        st.success("🎉 全书创作完成!")
    else:
        st.info("创作中... 请等待或重新点击侧栏按钮")
