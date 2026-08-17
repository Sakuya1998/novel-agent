import { AlertCircle, ArrowUpRight, Command, RefreshCw, Settings } from "lucide-react";
import { useState } from "react";
import { ChapterReader } from "./components/ChapterReader";
import { NovelSidebar } from "./components/NovelSidebar";
import { ModelSettingsDialog } from "./components/ModelSettingsDialog";
import { ReviewPanel } from "./components/ReviewPanel";
import { StageRail } from "./components/StageRail";
import { useWorkbench } from "./useWorkbench";

function App() {
  const workbench = useWorkbench();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { novel, state, error, isStreaming, lastNode } = workbench;
  const statusLabel = state?.status === "human_review" ? "等待人工审查" : state?.status === "completed" ? "创作完成" : state?.status === "running" ? "创作进行中" : state?.status === "legacy_read_only" ? "只读作品" : "尚未启动";

  return <div className="app-shell">
    <NovelSidebar novels={workbench.novels} selectedId={workbench.selectedId} isLoading={workbench.isLoading} isStreaming={isStreaming} deletingId={workbench.deletingId} onSelect={workbench.setSelectedId} onCreate={workbench.addNovel} onDelete={(item) => workbench.removeNovel(item.id)} />
    <main className="workspace">
      <header className="topbar"><div className="breadcrumb"><span>工作台</span><ArrowUpRight size={13} /><strong>{novel?.title || "选择一部作品"}</strong></div><div className="topbar-actions"><span className="connection-pill"><span className="status-dot online" />API 在线</span><button className="icon-button" title="模型设置" aria-label="模型设置" onClick={() => setSettingsOpen(true)}><Settings size={16} /></button><button className="icon-button" title="刷新当前作品" onClick={() => workbench.selectedId && window.location.reload()}><RefreshCw size={16} /></button><span className="command-key"><Command size={13} /> K</span></div></header>
      {error && <div className="global-error"><AlertCircle size={16} />{error}</div>}
      {!novel || !state ? <section className="welcome-state"><div className="welcome-mark">墨</div><span className="eyebrow">NOVEL AGENT / WORKBENCH</span><h1>让故事从第一行开始生长。</h1><p>选择左侧作品，或新建一部小说。创作进度、章节稿件和人工审查会在同一张工作台上持续保存。</p><button className="primary-button" onClick={() => document.querySelector<HTMLButtonElement>(".sidebar .icon-button")?.click()}>新建作品 <ArrowUpRight size={15} /></button></section> : <>
        <section className="work-header"><div><span className="eyebrow">CURRENT PROJECT</span><h1>{novel.title}</h1><p>{novel.inspiration}</p></div><div className="work-metrics"><div><span>进度</span><strong>{state.chapters_done}<em>/{state.total_chapters}</em></strong></div><div><span>当前阶段</span><strong>{statusLabel}</strong></div><div><span>风格</span><strong>{novel.style || "默认"}</strong></div></div></section>
        <StageRail lastNode={lastNode} status={state.status} currentPhase={state.current_phase} />
        <section className={`content-grid ${state.status === "human_review" ? "with-review" : ""}`}><ChapterReader draft={state.current_draft} chapters={novel.chapters || []} status={state.status} />{state.status === "human_review" ? <ReviewPanel draft={state.current_draft} issues={state.issues} persistenceError={state.persistence_error} disabled={isStreaming} onSubmit={workbench.resume} /> : <aside className="next-panel"><div className="section-kicker">NEXT ACTION</div><h2>{state.status === "completed" ? "这部作品已经完成" : state.status === "running" ? "创作正在推进" : "准备好开始了吗？"}</h2><p>{state.status === "completed" ? "所有已生成章节都已从后端定稿。" : state.status === "running" ? "后端正在执行 LangGraph 节点，完成后会自动更新这里。" : "启动创作后，系统会先构建世界观、角色和全书大纲。"}</p>{state.status !== "completed" && state.status !== "running" && state.status !== "legacy_read_only" && <button className="primary-button" onClick={() => workbench.run()} disabled={isStreaming}>开始/继续创作 <ArrowUpRight size={15} /></button>}</aside>}</section>
      </>}
    </main>
    <ModelSettingsDialog open={settingsOpen} isStreaming={isStreaming} onClose={() => setSettingsOpen(false)} />
  </div>;
}

export default App;
