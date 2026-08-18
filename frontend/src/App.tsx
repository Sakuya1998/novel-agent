import { Activity, AlertCircle, ArrowUpRight, BookKey, BrainCircuit, Command, Download, FlaskConical, GitBranch, RefreshCw, Settings, SlidersHorizontal, UserRound, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { ChapterReader } from "./components/ChapterReader";
import { CanonDialog } from "./components/CanonDialog";
import { NovelSidebar } from "./components/NovelSidebar";
import { ModelSettingsDialog } from "./components/ModelSettingsDialog";
import { ReviewPanel } from "./components/ReviewPanel";
import { RunControlPanel } from "./components/RunControlPanel";
import { PlanningReviewPanel } from "./components/PlanningReviewPanel";
import { StageRail } from "./components/StageRail";
import { BookAuditPanel } from "./components/BookAuditPanel";
import { CreativeBriefDialog } from "./components/CreativeBriefDialog";
import { ModelTraceDialog } from "./components/ModelTraceDialog";
import { EvaluationBenchmarkDialog } from "./components/EvaluationBenchmarkDialog";
import { AuthDialog } from "./components/AuthDialog";
import { MemoryQualityDialog } from "./components/MemoryQualityDialog";
import { ImportExportDialog } from "./components/ImportExportDialog";
import { MonitoringDialog } from "./components/MonitoringDialog";
import { getStoredAuthUser, loginAuth, logoutAuth, registerAuth } from "./api";
import { AGE_RATING_LABELS, POINT_OF_VIEW_LABELS } from "./creativeBrief";
import { useWorkbench } from "./useWorkbench";
import "./book-audit.css";

function App() {
  const workbench = useWorkbench();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [canonOpen, setCanonOpen] = useState(false);
  const [creativeBriefOpen, setCreativeBriefOpen] = useState(false);
  const [tracesOpen, setTracesOpen] = useState(false);
  const [benchmarksOpen, setBenchmarksOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [memoryQualityOpen, setMemoryQualityOpen] = useState(false);
  const [importExportOpen, setImportExportOpen] = useState(false);
  const [monitoringOpen, setMonitoringOpen] = useState(false);
  const [authUser] = useState(getStoredAuthUser);
  const { novel, state, error, isStreaming, lastNode } = workbench;
  const creativeBrief = novel?.creative_brief ?? state?.creative_brief;
  const statusLabel = state?.status === "blueprint_review" ? "等待蓝图审阅" : state?.status === "scene_review" ? "等待分镜审阅" : state?.status === "human_review" ? "等待人工审查" : state?.status === "completed" ? "创作完成" : state?.status === "running" ? "创作进行中" : state?.status === "interrupted" ? "运行已中断" : state?.status === "error" ? "运行失败" : state?.status === "legacy_read_only" ? "只读作品" : "尚未启动";
  useEffect(() => {
    if (error.includes("需要登录") || error.includes("会话无效")) setAuthOpen(true);
  }, [error]);

  return <div className="app-shell">
    <NovelSidebar novels={workbench.novels} selectedId={workbench.selectedId} isLoading={workbench.isLoading} isStreaming={isStreaming} deletingId={workbench.deletingId} onSelect={workbench.setSelectedId} onCreate={workbench.addNovel} onDelete={(item) => workbench.removeNovel(item.id)} />
    <main className="workspace">
      <header className="topbar"><div className="breadcrumb"><span>工作台</span><ArrowUpRight size={13} /><strong>{novel?.title || "选择一部作品"}</strong></div><div className="topbar-actions"><span className="connection-pill"><span className="status-dot online" />API 在线</span><button className="icon-button" title="运行状态与审计" aria-label="运行状态与审计" onClick={() => setMonitoringOpen(true)}><ShieldCheck size={16} /></button><button className="icon-button" title={authUser ? `${authUser.display_name || authUser.username} · ${authUser.role}` : "登录工作区"} aria-label="工作区身份" onClick={() => setAuthOpen(true)}><UserRound size={16} /></button><button className="icon-button" title="质量评测基准" aria-label="质量评测基准" onClick={() => { setBenchmarksOpen(true); void workbench.loadEvaluationBenchmarks(); }}><FlaskConical size={16} /></button><button className="icon-button" title="导入与导出" aria-label="导入与导出" onClick={() => setImportExportOpen(true)}><Download size={16} /></button>{novel && <><button className="icon-button" title="长期记忆质量" aria-label="长期记忆质量" onClick={() => setMemoryQualityOpen(true)}><BrainCircuit size={16} /></button><button className="icon-button" title="查看模型调用轨迹" aria-label="查看模型调用轨迹" onClick={() => { setTracesOpen(true); void workbench.loadModelTraces(); }}><Activity size={16} /></button><button className="icon-button" title="编辑创作约束" aria-label="编辑创作约束" onClick={() => setCreativeBriefOpen(true)}><SlidersHorizontal size={16} /></button><button className="icon-button" title="Canon 设定治理" aria-label="Canon 设定治理" onClick={() => setCanonOpen(true)}><BookKey size={16} /></button></>}<button className="icon-button" title="模型设置" aria-label="模型设置" onClick={() => setSettingsOpen(true)}><Settings size={16} /></button><button className="icon-button" title="刷新当前作品" onClick={() => workbench.selectedId && window.location.reload()}><RefreshCw size={16} /></button><span className="command-key"><Command size={13} /> K</span></div></header>
      {error && <div className="global-error"><AlertCircle size={16} />{error}</div>}
      {!novel || !state ? <section className="welcome-state"><div className="welcome-mark">墨</div><span className="eyebrow">NOVEL AGENT / WORKBENCH</span><h1>让故事从第一行开始生长。</h1><p>选择左侧作品，或新建一部小说。创作进度、章节稿件和人工审查会在同一张工作台上持续保存。</p><button className="primary-button" onClick={() => document.querySelector<HTMLButtonElement>(".sidebar .icon-button")?.click()}>新建作品 <ArrowUpRight size={15} /></button></section> : <>
        <section className="work-header"><div><span className="eyebrow">CURRENT PROJECT</span><h1>{novel.title}</h1><p>{novel.inspiration}</p></div><div className="work-metrics"><div><span>进度</span><strong>{state.chapters_done}<em>/{state.total_chapters}</em></strong></div><div><span>当前阶段</span><strong>{statusLabel}</strong></div><div><span>风格</span><strong>{novel.style || "默认"}</strong></div>{creativeBrief && <div><span>创作约束</span><strong>{POINT_OF_VIEW_LABELS[creativeBrief.point_of_view]}<em> / {AGE_RATING_LABELS[creativeBrief.age_rating]}</em></strong></div>}<div><span>设定记忆</span><strong>{(state.canon?.world_facts ?? 0) + (state.canon?.confirmed_facts ?? 0)}<em> 条事实</em></strong></div><div><span>长篇记忆</span><strong>{state.memory?.arcs ?? 0}<em> 幕 / {state.memory?.chapters ?? 0} 章</em></strong></div><div><span>剧情债务</span><strong>{state.canon?.open_threads ?? 0}<em>{state.canon?.overdue_threads ? ` / ${state.canon.overdue_threads} 逾期` : " 条开放"}</em></strong></div><div><span>模型用量</span><strong>{state.model_usage?.total_tokens ?? 0}<em> tokens</em></strong></div></div></section>
        <StageRail lastNode={lastNode} status={state.status} currentPhase={state.current_phase} />
        {state.replan_proposal?.status === "replanned" && <div className="replan-callout" role="status"><GitBranch size={16} /><div><strong>后续大纲已调整</strong><span>{state.replan_proposal.rationale || "系统根据最新定稿更新了未来章节。"}</span></div></div>}
        {state.replan_proposal?.status === "error" && <div className="replan-callout warning" role="status"><AlertCircle size={16} /><div><strong>后续大纲保持不变</strong><span>{state.replan_proposal.rationale || "重规划未应用，当前大纲继续有效。"}</span></div></div>}
        {state.status === "blueprint_review" || state.status === "scene_review" ? <PlanningReviewPanel reviewNode={state.status} worldBible={state.world_bible ?? ""} characters={state.characters ?? []} outline={state.outline ?? []} scenePlan={state.scene_plan ?? []} planningVersions={state.planning_versions ?? []} disabled={isStreaming} onSubmit={workbench.resume} onLoadVersion={workbench.loadPlanningVersion} onCompareVersions={workbench.comparePlanningVersions} /> : <section className={`content-grid ${state.status === "human_review" ? "with-review" : ""}`}><ChapterReader draft={state.current_draft} chapters={novel.chapters || []} status={state.status} />{state.status === "human_review" ? <ReviewPanel draft={state.current_draft} issues={state.issues ?? []} conflicts={state.conflicts ?? []} qualityReport={state.quality_report ?? undefined} persistenceError={state.persistence_error ?? ""} versions={state.versions ?? []} evaluations={state.evaluations ?? []} candidates={state.chapter_candidates ?? []} disabled={isStreaming} onSubmit={workbench.resume} onApplyCanon={workbench.updateCanon} onGenerateCandidates={workbench.generateCandidates} onCompareVersions={workbench.compareVersions} onEvaluateVersion={workbench.evaluateVersion} onSetEvaluationBaseline={workbench.setEvaluationBaseline} onCompareEvaluations={workbench.compareEvaluations} /> : state.status === "completed" && state.book_audit ? <BookAuditPanel report={state.book_audit} totalChapters={state.total_chapters} disabled={isStreaming} onStartRevision={workbench.startBookRevision} /> : <RunControlPanel status={state.status} job={state.run_job} disabled={state.status === "running" ? Boolean(state.run_job?.cancel_requested) : isStreaming} onRun={() => workbench.run()} onCancel={workbench.cancelJob} />}</section>}
      </>}
    </main>
    <CanonDialog open={canonOpen} novelId={workbench.selectedId} editable={state?.status === "human_review"} disabled={isStreaming} currentChapter={state?.current_chapter} scenePlan={state?.current_draft.scene_plan} onClose={() => setCanonOpen(false)} onSubmit={workbench.updateCanon} />
    <CreativeBriefDialog open={creativeBriefOpen} brief={novel?.creative_brief ?? state?.creative_brief} version={novel?.creative_brief_version ?? state?.creative_brief_version} versions={workbench.creativeBriefVersions} disabled={isStreaming} onClose={() => setCreativeBriefOpen(false)} onSubmit={workbench.updateBrief} />
    <ModelTraceDialog open={tracesOpen} traces={workbench.modelTraces} onRefresh={workbench.loadModelTraces} onClose={() => setTracesOpen(false)} />
    <EvaluationBenchmarkDialog open={benchmarksOpen} runs={workbench.evaluationBenchmarks} onRun={workbench.runBenchmark} onClose={() => setBenchmarksOpen(false)} />
    <MemoryQualityDialog open={memoryQualityOpen} history={workbench.memoryQuality} onRefresh={workbench.loadMemoryQuality} onEvaluate={workbench.runMemoryQuality} onRebuild={workbench.rebuildMemoryIndex} onClose={() => setMemoryQualityOpen(false)} />
    <ImportExportDialog open={importExportOpen} novelTitle={novel?.title ?? ""} onClose={() => setImportExportOpen(false)} onExport={workbench.exportNovel} onImport={workbench.importNovel} />
    <AuthDialog open={authOpen} currentUser={authUser} onLogin={async (identifier, password) => { const session = await loginAuth(identifier, password); window.location.reload(); return session; }} onRegister={async (payload) => { const session = await registerAuth(payload); window.location.reload(); return session; }} onLogout={async () => { await logoutAuth(); window.location.reload(); }} onClose={() => setAuthOpen(false)} />
    <MonitoringDialog open={monitoringOpen} onClose={() => setMonitoringOpen(false)} />
    <ModelSettingsDialog open={settingsOpen} isStreaming={isStreaming} onClose={() => setSettingsOpen(false)} />
  </div>;
}

export default App;
