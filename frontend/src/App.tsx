import { AlertCircle, GitBranch } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getAuthStatus, loginAuth, logoutAuth, registerAuth } from "./api";
import { AuthDialog } from "./components/AuthDialog";
import { BookAuditPanel } from "./components/BookAuditPanel";
import { CanonDialog } from "./components/CanonDialog";
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
import { WritingWorkspace, type WritingReaderFocus } from "./components/WritingWorkspace";
import { StageRail } from "./components/StageRail";
import { WorkspaceHeader } from "./components/WorkspaceHeader";
import { WorkspaceNav, type WorkspaceView } from "./components/WorkspaceNav";
import { useServiceStatus } from "./useServiceStatus";
import { useWorkbench } from "./useWorkbench";
import { useReviewWorkflow } from "./useReviewWorkflow";
import type { CanonOperation } from "./types";
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
  const [authEnabled, setAuthEnabled] = useState<boolean>();
  const [authUser, setAuthUser] = useState<Awaited<ReturnType<typeof getAuthStatus>>["user"]>(null);
  const workbench = useWorkbench(authEnabled === false || (authEnabled === true && authUser !== null));
  const serviceStatus = useServiceStatus();
  const [activeDialog, setActiveDialog] = useState<DialogName>();
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("write");
  const [readerFocus, setReaderFocus] = useState<WritingReaderFocus>();
  const [createOpen, setCreateOpen] = useState(false);
  const { novel, state, error, isStreaming, lastNode } = workbench;
  const reviewWorkflow = useReviewWorkflow({
    novelId: workbench.selectedId ?? "",
    chapterNumber: state?.current_draft.chapter_number ?? 0,
    onSubmit: workbench.resume,
  });
  const { runAction } = reviewWorkflow;
  const { updateCanon } = workbench;
  const applyCanon = useCallback((operation: CanonOperation) =>
    runAction("canon", () => updateCanon(operation), undefined, true), [runAction, updateCanon]);
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
                reviewScope={`${novel.id}:${state.status}:${state.current_chapter}`}
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

            {workspaceView === "write" ? <WritingWorkspace
              novel={novel}
              state={state}
              readerFocus={readerFocus}
              onReaderFocusChange={setReaderFocus}
              connectionStatus={workbench.connectionStatus}
              lastNode={lastNode}
              isStreaming={isStreaming}
              onRun={workbench.run}
              onCancel={workbench.cancelJob}
              onRetry={workbench.retryRunConnection}
              reviewWorkflow={reviewWorkflow}
              onApplyCanon={workbench.updateCanon}
              onGenerateCandidates={workbench.generateCandidates}
              onCompareVersions={workbench.compareVersions}
              onEvaluateVersion={workbench.evaluateVersion}
              onSetEvaluationBaseline={workbench.setEvaluationBaseline}
              onCompareEvaluations={workbench.compareEvaluations}
              onOpenPlanning={() => setWorkspaceView("plan")}
              onOpenQuality={() => setWorkspaceView("quality")}
            /> : null}
          </>
        )}
      </main>

      <CanonDialog open={activeDialog === "canon"} novelId={workbench.selectedId} editable={state?.status === "human_review"} disabled={isStreaming || Boolean(reviewWorkflow.busyAction)} currentChapter={state?.current_chapter} scenePlan={state?.current_draft.scene_plan} onClose={() => setActiveDialog(undefined)} onSubmit={applyCanon} />
      <CreativeBriefDialog open={activeDialog === "brief"} brief={creativeBrief} version={novel?.creative_brief_version ?? state?.creative_brief_version} versions={workbench.creativeBriefVersions} disabled={isStreaming} onClose={() => setActiveDialog(undefined)} onSubmit={workbench.updateBrief} />
      <ModelTraceDialog open={activeDialog === "traces"} traces={workbench.modelTraces} onRefresh={workbench.loadModelTraces} onClose={() => setActiveDialog(undefined)} />
      <EvaluationBenchmarkDialog open={activeDialog === "benchmarks"} runs={workbench.evaluationBenchmarks} onRun={workbench.runBenchmark} onClose={() => setActiveDialog(undefined)} />
      <MemoryQualityDialog open={activeDialog === "memory"} history={workbench.memoryQuality} onRefresh={workbench.loadMemoryQuality} onEvaluate={workbench.runMemoryQuality} onRebuild={workbench.rebuildMemoryIndex} onClose={() => setActiveDialog(undefined)} />
      <ImportExportDialog open={activeDialog === "transfer"} novelTitle={novel?.title ?? ""} onClose={() => setActiveDialog(undefined)} onExport={workbench.exportNovel} onImport={workbench.importNovel} />
      <AuthDialog open={authEnabled === true && activeDialog === "auth"} currentUser={authUser} onLogin={async (identifier, password) => { const session = await loginAuth(identifier, password); setAuthUser(session.user); setActiveDialog(undefined); return session; }} onRegister={async (payload) => { const session = await registerAuth(payload); setAuthUser(session.user); setActiveDialog(undefined); return session; }} onLogout={async () => { await logoutAuth(); setAuthUser(null); setActiveDialog(undefined); }} onClose={() => setActiveDialog(undefined)} />
      <MonitoringDialog open={activeDialog === "monitoring"} onClose={() => setActiveDialog(undefined)} />
      <ModelSettingsDialog open={activeDialog === "settings"} isStreaming={isStreaming} onClose={() => setActiveDialog(undefined)} />
    </div>
  );
}

export default App;
