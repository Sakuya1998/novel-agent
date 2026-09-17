import { AlertCircle, ArrowRight, CheckCircle2, GitBranch } from "lucide-react";
import { useEffect, useState } from "react";
import { getAuthStatus, loginAuth, logoutAuth, registerAuth } from "./api";
import { AuthDialog } from "./components/AuthDialog";
import { BookAuditPanel } from "./components/BookAuditPanel";
import { CanonDialog } from "./components/CanonDialog";
import { ChapterReader } from "./components/ChapterReader";
import { CreativeBriefDialog } from "./components/CreativeBriefDialog";
import { EmptyWorkspace } from "./components/EmptyWorkspace";
import { EvaluationBenchmarkDialog } from "./components/EvaluationBenchmarkDialog";
import { ImportExportDialog } from "./components/ImportExportDialog";
import { KnowledgeWorkspace } from "./components/KnowledgeWorkspace";
import { MemoryQualityDialog } from "./components/MemoryQualityDialog";
import { ModelSettingsDialog } from "./components/ModelSettingsDialog";
import { ModelTraceDialog } from "./components/ModelTraceDialog";
import { MonitoringDialog } from "./components/MonitoringDialog";
import { NovelSidebar } from "./components/NovelSidebar";
import { PlanningReviewPanel } from "./components/PlanningReviewPanel";
import { PlanningWorkspace } from "./components/PlanningWorkspace";
import { ProjectOverview } from "./components/ProjectOverview";
import { QualityWorkspace } from "./components/QualityWorkspace";
import { ReviewWorkspace } from "./components/ReviewWorkspace";
import { RunControlPanel } from "./components/RunControlPanel";
import { StageRail } from "./components/StageRail";
import { WorkspaceHeader } from "./components/WorkspaceHeader";
import { WorkspaceNav, type WorkspaceView } from "./components/WorkspaceNav";
import { useServiceStatus } from "./useServiceStatus";
import { useWorkbench } from "./useWorkbench";
import "./book-audit.css";

type DialogName = "settings" | "canon" | "brief" | "traces" | "benchmarks" | "auth" | "memory" | "transfer" | "monitoring";

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

function errorCopy(error: string) {
  if (/请求失败 \(50[234]\)|failed to fetch|networkerror/i.test(error)) return "无法连接后端服务，请确认服务已经启动。";
  return error;
}

function App() {
  const workbench = useWorkbench();
  const serviceStatus = useServiceStatus();
  const [activeDialog, setActiveDialog] = useState<DialogName>();
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("write");
  const [createOpen, setCreateOpen] = useState(false);
  const [authEnabled, setAuthEnabled] = useState<boolean>();
  const [authUser, setAuthUser] = useState<Awaited<ReturnType<typeof getAuthStatus>>["user"]>(null);
  const [reviewFocus, setReviewFocus] = useState<{ sceneNumber?: number; request: number }>({ request: 0 });
  const { novel, state, error, isStreaming, lastNode } = workbench;
  const creativeBrief = novel?.creative_brief ?? state?.creative_brief;
  const planningReview = state?.status === "blueprint_review" || state?.status === "scene_review";

  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((status) => {
        if (!active) return;
        setAuthEnabled(status.enabled);
        setAuthUser(status.enabled ? status.user : null);
        if (!status.enabled) setActiveDialog((current) => current === "auth" ? undefined : current);
      })
      .catch(() => {
        if (active) setAuthEnabled(undefined);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (authEnabled === true && (error.includes("需要登录") || error.includes("会话无效"))) setActiveDialog("auth");
  }, [authEnabled, error]);

  useEffect(() => {
    setWorkspaceView(planningReview ? "plan" : "write");
  }, [workbench.selectedId, planningReview]);

  function openBenchmarks() {
    setActiveDialog("benchmarks");
    void workbench.loadEvaluationBenchmarks();
  }

  function openTraces() {
    setActiveDialog("traces");
    void workbench.loadModelTraces();
  }

  return (
    <div className="app-shell">
      <NovelSidebar
        novels={workbench.novels}
        selectedId={workbench.selectedId}
        isLoading={workbench.isLoading}
        isStreaming={isStreaming}
        deletingId={workbench.deletingId}
        serviceStatus={serviceStatus}
        createOpen={createOpen}
        onCreateOpenChange={setCreateOpen}
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
          onOpenAuth={() => setActiveDialog("auth")}
          onOpenMonitoring={() => setActiveDialog("monitoring")}
          onOpenBenchmarks={openBenchmarks}
          onOpenImportExport={() => setActiveDialog("transfer")}
          onOpenTraces={openTraces}
          onOpenSettings={() => setActiveDialog("settings")}
          onRefresh={workbench.selectedId ? () => window.location.reload() : undefined}
        />
        {error ? <div className="global-error" role="alert" aria-live="assertive"><AlertCircle size={16} /><span>{errorCopy(error)}</span><button type="button" onClick={() => window.location.reload()}>重试</button></div> : null}

        {!novel || !state ? (
          <EmptyWorkspace serviceStatus={serviceStatus} onCreate={() => setCreateOpen(true)} onImport={() => setActiveDialog("transfer")} onSettings={() => setActiveDialog("settings")} />
        ) : (
          <>
            <ProjectOverview novel={novel} state={state} statusLabel={statusLabel(state.status)} />
            <StageRail lastNode={lastNode} status={state.status} currentPhase={state.current_phase} />
            <WorkspaceNav active={workspaceView} status={state.status} issueCount={state.conflicts?.length || state.issues.length} onChange={setWorkspaceView} />

            {state.replan_proposal?.status === "replanned" ? <div className="replan-callout" role="status"><GitBranch size={16} /><div><strong>后续大纲已调整</strong><span>{state.replan_proposal.rationale || "系统根据最新定稿更新了未来章节。"}</span></div></div> : null}
            {state.replan_proposal?.status === "error" ? <div className="replan-callout warning" role="status"><AlertCircle size={16} /><div><strong>后续大纲保持不变</strong><span>{state.replan_proposal.rationale || "重规划未应用，当前大纲继续有效。"}</span></div></div> : null}

            {workspaceView === "plan" ? planningReview ? (
              <PlanningReviewPanel
                reviewNode={state.status as "blueprint_review" | "scene_review"}
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
            ) : <PlanningWorkspace state={state} /> : null}

            {workspaceView === "knowledge" ? <KnowledgeWorkspace novel={novel} state={state} onOpenBrief={() => setActiveDialog("brief")} onOpenCanon={() => setActiveDialog("canon")} onOpenMemory={() => setActiveDialog("memory")} /> : null}

            {workspaceView === "quality" ? state.status === "completed" && state.book_audit ? (
              <div className="workspace-book-audit"><BookAuditPanel report={state.book_audit} totalChapters={state.total_chapters} disabled={isStreaming} onStartRevision={workbench.startBookRevision} /></div>
            ) : <QualityWorkspace state={state} onOpenMonitoring={() => setActiveDialog("monitoring")} onOpenBenchmarks={openBenchmarks} onOpenTraces={openTraces} /> : null}

            {workspaceView === "write" ? (
              <section className={`content-grid ${state.status === "human_review" ? "with-review" : ""}`}>
                <ChapterReader draft={state.current_draft} chapters={novel.chapters || []} status={state.status} selectedSceneNumber={reviewFocus.sceneNumber} focusRequest={reviewFocus.request} />
                {state.status === "human_review" ? (
                  <ReviewWorkspace
                    novelId={novel.id}
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
                    onFocusReader={(sceneNumber, request) => setReviewFocus({ sceneNumber, request })}
                  />
                ) : planningReview ? (
                  <aside className="next-panel review-required-panel"><div className="section-kicker">REVIEW REQUIRED</div><CheckCircle2 size={21} /><h2>规划等待确认</h2><p>批准当前蓝图或分镜后，正文创作才会继续。</p><button className="primary-button full-width" type="button" onClick={() => setWorkspaceView("plan")}>前往审阅<ArrowRight size={15} /></button></aside>
                ) : state.status === "completed" && state.book_audit ? (
                  <aside className="next-panel review-required-panel completed"><div className="section-kicker">MANUSCRIPT COMPLETE</div><CheckCircle2 size={21} /><h2>全书已经完成</h2><p>终审报告已生成，可以检查全书质量或发起返修。</p><button className="secondary-button full-width" type="button" onClick={() => setWorkspaceView("quality")}>查看终审<ArrowRight size={15} /></button></aside>
                ) : (
                  <RunControlPanel status={state.status} job={state.run_job} disabled={state.status === "running" ? Boolean(state.run_job?.cancel_requested) : isStreaming} onRun={() => workbench.run()} onCancel={workbench.cancelJob} />
                )}
              </section>
            ) : null}
          </>
        )}
      </main>

      <CanonDialog open={activeDialog === "canon"} novelId={workbench.selectedId} editable={state?.status === "human_review"} disabled={isStreaming} currentChapter={state?.current_chapter} scenePlan={state?.current_draft.scene_plan} onClose={() => setActiveDialog(undefined)} onSubmit={workbench.updateCanon} />
      <CreativeBriefDialog open={activeDialog === "brief"} brief={creativeBrief} version={novel?.creative_brief_version ?? state?.creative_brief_version} versions={workbench.creativeBriefVersions} disabled={isStreaming} onClose={() => setActiveDialog(undefined)} onSubmit={workbench.updateBrief} />
      <ModelTraceDialog open={activeDialog === "traces"} traces={workbench.modelTraces} onRefresh={workbench.loadModelTraces} onClose={() => setActiveDialog(undefined)} />
      <EvaluationBenchmarkDialog open={activeDialog === "benchmarks"} runs={workbench.evaluationBenchmarks} onRun={workbench.runBenchmark} onClose={() => setActiveDialog(undefined)} />
      <MemoryQualityDialog open={activeDialog === "memory"} history={workbench.memoryQuality} onRefresh={workbench.loadMemoryQuality} onEvaluate={workbench.runMemoryQuality} onRebuild={workbench.rebuildMemoryIndex} onClose={() => setActiveDialog(undefined)} />
      <ImportExportDialog open={activeDialog === "transfer"} novelTitle={novel?.title ?? ""} onClose={() => setActiveDialog(undefined)} onExport={workbench.exportNovel} onImport={workbench.importNovel} />
      <AuthDialog open={authEnabled === true && activeDialog === "auth"} currentUser={authUser} onLogin={async (identifier, password) => { const session = await loginAuth(identifier, password); window.location.reload(); return session; }} onRegister={async (payload) => { const session = await registerAuth(payload); window.location.reload(); return session; }} onLogout={async () => { await logoutAuth(); window.location.reload(); }} onClose={() => setActiveDialog(undefined)} />
      <MonitoringDialog open={activeDialog === "monitoring"} onClose={() => setActiveDialog(undefined)} />
      <ModelSettingsDialog open={activeDialog === "settings"} isStreaming={isStreaming} onClose={() => setActiveDialog(undefined)} />
    </div>
  );
}

export default App;
