import { AlertCircle, ArrowUpRight, GitBranch } from "lucide-react";
import { useEffect, useState } from "react";
import { getAuthStatus, loginAuth, logoutAuth, registerAuth } from "./api";
import { AuthDialog } from "./components/AuthDialog";
import { BookAuditPanel } from "./components/BookAuditPanel";
import { CanonDialog } from "./components/CanonDialog";
import { ChapterReader } from "./components/ChapterReader";
import { CreativeBriefDialog } from "./components/CreativeBriefDialog";
import { EvaluationBenchmarkDialog } from "./components/EvaluationBenchmarkDialog";
import { ImportExportDialog } from "./components/ImportExportDialog";
import { MemoryQualityDialog } from "./components/MemoryQualityDialog";
import { ModelSettingsDialog } from "./components/ModelSettingsDialog";
import { ModelTraceDialog } from "./components/ModelTraceDialog";
import { MonitoringDialog } from "./components/MonitoringDialog";
import { NovelSidebar } from "./components/NovelSidebar";
import { PlanningReviewPanel } from "./components/PlanningReviewPanel";
import { ProjectOverview } from "./components/ProjectOverview";
import { ReviewPanel } from "./components/ReviewPanel";
import { RunControlPanel } from "./components/RunControlPanel";
import { StageRail } from "./components/StageRail";
import { WorkspaceHeader } from "./components/WorkspaceHeader";
import { useServiceStatus } from "./useServiceStatus";
import { useWorkbench } from "./useWorkbench";
import "./book-audit.css";

function statusLabel(status?: string) {
  const labels: Record<string, string> = {
    blueprint_review: "等待蓝图审阅",
    scene_review: "等待分镜审阅",
    human_review: "等待人工审查",
    completed: "创作完成",
    running: "创作进行中",
    interrupted: "运行已中断",
    error: "运行失败",
    legacy_read_only: "只读作品",
    idle: "准备开始",
  };
  return labels[status ?? ""] ?? "尚未启动";
}

function App() {
  const workbench = useWorkbench();
  const serviceStatus = useServiceStatus();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [canonOpen, setCanonOpen] = useState(false);
  const [creativeBriefOpen, setCreativeBriefOpen] = useState(false);
  const [tracesOpen, setTracesOpen] = useState(false);
  const [benchmarksOpen, setBenchmarksOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [memoryQualityOpen, setMemoryQualityOpen] = useState(false);
  const [importExportOpen, setImportExportOpen] = useState(false);
  const [monitoringOpen, setMonitoringOpen] = useState(false);
  const [authEnabled, setAuthEnabled] = useState<boolean>();
  const [authUser, setAuthUser] = useState<Awaited<ReturnType<typeof getAuthStatus>>["user"]>(null);
  const { novel, state, error, isStreaming, lastNode } = workbench;
  const creativeBrief = novel?.creative_brief ?? state?.creative_brief;

  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((status) => {
        if (!active) return;
        setAuthEnabled(status.enabled);
        setAuthUser(status.enabled ? status.user : null);
        if (!status.enabled) setAuthOpen(false);
      })
      .catch(() => {
        if (active) setAuthEnabled(undefined);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (authEnabled === true && (error.includes("需要登录") || error.includes("会话无效"))) setAuthOpen(true);
  }, [authEnabled, error]);

  return (
    <div className="app-shell">
      <NovelSidebar
        novels={workbench.novels}
        selectedId={workbench.selectedId}
        isLoading={workbench.isLoading}
        isStreaming={isStreaming}
        deletingId={workbench.deletingId}
        serviceStatus={serviceStatus}
        onSelect={workbench.setSelectedId}
        onCreate={workbench.addNovel}
        onDelete={(item) => workbench.removeNovel(item.id)}
      />
      <main className="workspace">
        <WorkspaceHeader
          projectTitle={novel?.title}
          serviceStatus={serviceStatus}
          authEnabled={authEnabled}
          authUser={authUser}
          onOpenAuth={() => setAuthOpen(true)}
          onOpenMonitoring={() => setMonitoringOpen(true)}
          onOpenBenchmarks={() => { setBenchmarksOpen(true); void workbench.loadEvaluationBenchmarks(); }}
          onOpenImportExport={() => setImportExportOpen(true)}
          onOpenTraces={() => { setTracesOpen(true); void workbench.loadModelTraces(); }}
          onOpenSettings={() => setSettingsOpen(true)}
          onRefresh={workbench.selectedId ? () => window.location.reload() : undefined}
        />
        {error && <div className="global-error" role="alert" aria-live="assertive"><AlertCircle size={16} />{error}</div>}

        {!novel || !state ? (
          <section className="welcome-state">
            <div className="welcome-mark"><span>墨</span></div>
            <span className="eyebrow">NOVEL AGENT / WORKBENCH</span>
            <h1>把一个念头，推进成一部完整的小说。</h1>
            <p>在这里管理作品、推进章节、审阅生成内容，并让每一次修改都留下可追溯的上下文。</p>
            <button className="primary-button" onClick={() => document.querySelector<HTMLButtonElement>(".sidebar .icon-button")?.click()}>
              新建第一部作品 <ArrowUpRight size={15} />
            </button>
          </section>
        ) : (
          <>
            <ProjectOverview
              novel={novel}
              state={state}
              statusLabel={statusLabel(state.status)}
              onOpenBrief={() => setCreativeBriefOpen(true)}
              onOpenCanon={() => setCanonOpen(true)}
              onOpenMemory={() => setMemoryQualityOpen(true)}
            />
            <StageRail lastNode={lastNode} status={state.status} currentPhase={state.current_phase} />
            {state.replan_proposal?.status === "replanned" && (
              <div className="replan-callout" role="status"><GitBranch size={16} /><div><strong>后续大纲已调整</strong><span>{state.replan_proposal.rationale || "系统根据最新定稿更新了未来章节。"}</span></div></div>
            )}
            {state.replan_proposal?.status === "error" && (
              <div className="replan-callout warning" role="status"><AlertCircle size={16} /><div><strong>后续大纲保持不变</strong><span>{state.replan_proposal.rationale || "重规划未应用，当前大纲继续有效。"}</span></div></div>
            )}
            {state.status === "blueprint_review" || state.status === "scene_review" ? (
              <PlanningReviewPanel
                reviewNode={state.status}
                worldBible={state.world_bible ?? ""}
                characters={state.characters ?? []}
                outline={state.outline ?? []}
                scenePlan={state.scene_plan ?? []}
                planningVersions={state.planning_versions ?? []}
                disabled={isStreaming}
                onSubmit={workbench.resume}
                onLoadVersion={workbench.loadPlanningVersion}
                onCompareVersions={workbench.comparePlanningVersions}
              />
            ) : (
              <section className={`content-grid ${state.status === "human_review" ? "with-review" : ""}`}>
                <ChapterReader draft={state.current_draft} chapters={novel.chapters || []} status={state.status} />
                {state.status === "human_review" ? (
                  <ReviewPanel
                    draft={state.current_draft}
                    issues={state.issues ?? []}
                    conflicts={state.conflicts ?? []}
                    qualityReport={state.quality_report ?? undefined}
                    persistenceError={state.persistence_error ?? ""}
                    versions={state.versions ?? []}
                    evaluations={state.evaluations ?? []}
                    candidates={state.chapter_candidates ?? []}
                    disabled={isStreaming}
                    onSubmit={workbench.resume}
                    onApplyCanon={workbench.updateCanon}
                    onGenerateCandidates={workbench.generateCandidates}
                    onCompareVersions={workbench.compareVersions}
                    onEvaluateVersion={workbench.evaluateVersion}
                    onSetEvaluationBaseline={workbench.setEvaluationBaseline}
                    onCompareEvaluations={workbench.compareEvaluations}
                  />
                ) : state.status === "completed" && state.book_audit ? (
                  <BookAuditPanel report={state.book_audit} totalChapters={state.total_chapters} disabled={isStreaming} onStartRevision={workbench.startBookRevision} />
                ) : (
                  <RunControlPanel status={state.status} job={state.run_job} disabled={state.status === "running" ? Boolean(state.run_job?.cancel_requested) : isStreaming} onRun={() => workbench.run()} onCancel={workbench.cancelJob} />
                )}
              </section>
            )}
          </>
        )}
      </main>

      <CanonDialog open={canonOpen} novelId={workbench.selectedId} editable={state?.status === "human_review"} disabled={isStreaming} currentChapter={state?.current_chapter} scenePlan={state?.current_draft.scene_plan} onClose={() => setCanonOpen(false)} onSubmit={workbench.updateCanon} />
      <CreativeBriefDialog open={creativeBriefOpen} brief={creativeBrief} version={novel?.creative_brief_version ?? state?.creative_brief_version} versions={workbench.creativeBriefVersions} disabled={isStreaming} onClose={() => setCreativeBriefOpen(false)} onSubmit={workbench.updateBrief} />
      <ModelTraceDialog open={tracesOpen} traces={workbench.modelTraces} onRefresh={workbench.loadModelTraces} onClose={() => setTracesOpen(false)} />
      <EvaluationBenchmarkDialog open={benchmarksOpen} runs={workbench.evaluationBenchmarks} onRun={workbench.runBenchmark} onClose={() => setBenchmarksOpen(false)} />
      <MemoryQualityDialog open={memoryQualityOpen} history={workbench.memoryQuality} onRefresh={workbench.loadMemoryQuality} onEvaluate={workbench.runMemoryQuality} onRebuild={workbench.rebuildMemoryIndex} onClose={() => setMemoryQualityOpen(false)} />
      <ImportExportDialog open={importExportOpen} novelTitle={novel?.title ?? ""} onClose={() => setImportExportOpen(false)} onExport={workbench.exportNovel} onImport={workbench.importNovel} />
      <AuthDialog open={authEnabled === true && authOpen} currentUser={authUser} onLogin={async (identifier, password) => { const session = await loginAuth(identifier, password); window.location.reload(); return session; }} onRegister={async (payload) => { const session = await registerAuth(payload); window.location.reload(); return session; }} onLogout={async () => { await logoutAuth(); window.location.reload(); }} onClose={() => setAuthOpen(false)} />
      <MonitoringDialog open={monitoringOpen} onClose={() => setMonitoringOpen(false)} />
      <ModelSettingsDialog open={settingsOpen} isStreaming={isStreaming} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

export default App;
