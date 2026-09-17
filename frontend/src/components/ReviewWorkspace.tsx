import { AlertTriangle, Check, FileClock, Gauge, Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import type { CanonOperation, ChapterCandidate, ChapterEvaluation, ChapterVersion, ConflictExplanation, ConsistencyIssue, Draft, EvaluationComparison, QualityGateReport, ReviewSubmission } from "../types";
import { useReviewWorkflow, type ReviewBusyAction, type ReviewTab } from "../useReviewWorkflow";
import { ChapterCandidatesPanel } from "./ChapterCandidatesPanel";
import { ChapterEvaluationPanel } from "./ChapterEvaluationPanel";
import { ReviewDecisionPanel } from "./ReviewDecisionPanel";
import { ReviewIssuesPanel } from "./ReviewIssuesPanel";
import { VersionHistory } from "./VersionHistory";

export interface ReviewWorkspaceProps {
  novelId: string;
  draft: Draft;
  issues: ConsistencyIssue[];
  conflicts?: ConflictExplanation[];
  qualityReport?: QualityGateReport;
  persistenceError: string;
  versions?: ChapterVersion[];
  evaluations?: ChapterEvaluation[];
  candidates?: ChapterCandidate[];
  disabled: boolean;
  onSubmit: (review: ReviewSubmission) => Promise<void>;
  onApplyCanon?: (operation: CanonOperation) => Promise<void>;
  onGenerateCandidates?: (count: number, instruction: string) => Promise<void>;
  onCompareVersions?: (fromVersion: number, toVersion: number) => Promise<string>;
  onEvaluateVersion?: (versionNumber: number, includeJudge: boolean) => Promise<ChapterEvaluation>;
  onSetEvaluationBaseline?: (evaluationId: number) => Promise<ChapterEvaluation>;
  onCompareEvaluations?: (fromVersion: number, toVersion: number) => Promise<EvaluationComparison>;
  onFocusReader?: (sceneNumber: number | undefined, focusRequest: number) => void;
}

const TAB_LABELS: Record<ReviewTab, string> = {
  decision: "决定",
  issues: "问题",
  candidates: "候选稿",
  versions: "版本",
};

export function ReviewWorkspace({
  novelId,
  draft,
  issues,
  conflicts = [],
  qualityReport,
  persistenceError,
  versions = [],
  evaluations = [],
  candidates = [],
  disabled,
  onSubmit,
  onApplyCanon,
  onGenerateCandidates,
  onCompareVersions,
  onEvaluateVersion,
  onSetEvaluationBaseline,
  onCompareEvaluations,
  onFocusReader,
}: ReviewWorkspaceProps) {
  const chapterNumber = draft.chapter_number ?? 0;
  const workflow = useReviewWorkflow({ novelId, chapterNumber, onSubmit });
  const [canonBusy, setCanonBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const pendingScene = useRef<number | undefined>(undefined);
  const activeBusyAction: ReviewBusyAction = canonBusy ? "canon" : workflow.busyAction;

  const hasIssues = issues.length > 0 || conflicts.length > 0 || Boolean(qualityReport) || Boolean(persistenceError);
  const hasVersionCommands = Boolean(onCompareVersions || onEvaluateVersion || onSetEvaluationBaseline || onCompareEvaluations);
  const hasVersions = versions.length > 0 || evaluations.length > 0 || hasVersionCommands;
  const hasEvaluationSurface = versions.length > 0 || evaluations.length > 0;
  const tabs = ([
    { id: "decision" as const, icon: Check },
    ...(hasIssues ? [{ id: "issues" as const, icon: AlertTriangle }] : []),
    ...((onGenerateCandidates || candidates.length > 0) ? [{ id: "candidates" as const, icon: Sparkles }] : []),
    ...(hasVersions ? [{ id: "versions" as const, icon: FileClock }] : []),
  ]);
  const activeTab = tabs.some((tab) => tab.id === workflow.activeTab) ? workflow.activeTab : "decision";
  const activeLabel = TAB_LABELS[activeTab];
  const workspaceError = workflow.error || actionError;
  const compareVersions = onCompareVersions ?? (async () => "");
  const evaluateVersion = onEvaluateVersion ?? (async () => { throw new Error("章节评测不可用"); });
  const setEvaluationBaseline = onSetEvaluationBaseline ?? (async () => { throw new Error("设置基准不可用"); });
  const compareEvaluations = onCompareEvaluations ?? (async () => { throw new Error("回归比较不可用"); });

  async function applyCanon(operation: CanonOperation) {
    if (!onApplyCanon) return;
    setCanonBusy(true);
    try {
      await onApplyCanon(operation);
    } finally {
      setCanonBusy(false);
    }
  }

  function returnToDecision() {
    setActionError("");
    workflow.setActiveTab("decision");
    onFocusReader?.(pendingScene.current, workflow.focusRequest + 1);
    pendingScene.current = undefined;
  }

  const decisionContent = <div className="review-decision-dock">
    <ReviewDecisionPanel
      scenePlan={draft.scene_plan ?? []}
      sceneNumber={workflow.sceneNumber}
      feedback={workflow.feedback}
      busyAction={activeBusyAction}
      disabled={disabled}
      error={workflow.error}
      onSceneChange={workflow.selectScene}
      onFeedbackChange={workflow.setFeedback}
      onRevise={workflow.submitRevision}
      onApprove={workflow.approve}
    />
  </div>;

  let activeContent: React.ReactNode = decisionContent;
  if (activeTab === "issues") {
    activeContent = <ReviewIssuesPanel issues={issues} conflicts={conflicts} qualityReport={qualityReport} persistenceError={persistenceError} disabled={disabled} busyAction={activeBusyAction} onApplyCanon={onApplyCanon ? applyCanon : undefined} onRepairFeedback={(feedback) => workflow.replaceDraft({ feedback })} onError={(reason) => setActionError(reason instanceof Error ? reason.message : "审稿操作失败")} />;
  } else if (activeTab === "candidates") {
    activeContent = <ChapterCandidatesPanel
      candidates={candidates}
      currentContent={draft.content ?? ""}
      disabled={disabled || Boolean(activeBusyAction)}
      onGenerate={onGenerateCandidates ?? (async () => undefined)}
      onSelect={async (candidateId) => {
        pendingScene.current = workflow.sceneNumber;
        await workflow.replaceDraft({ feedback: "candidate", candidate_id: candidateId });
      }}
      onSelected={returnToDecision}
      onError={(reason) => setActionError(reason instanceof Error ? reason.message : "候选稿采用失败")}
    />;
  } else if (activeTab === "versions") {
    activeContent = <>
      {versions.length > 0 ? <VersionHistory
          versions={versions}
          disabled={disabled || Boolean(activeBusyAction)}
          onCompare={compareVersions}
          onRestore={async (versionNumber) => {
            pendingScene.current = workflow.sceneNumber;
            await workflow.replaceDraft({ feedback: "restore", version_number: versionNumber });
          }}
          onRestored={returnToDecision}
          onError={(reason) => setActionError(reason instanceof Error ? reason.message : "版本恢复失败")}
        /> : <div className="review-empty-state">暂无可用版本</div>}
      {hasEvaluationSurface ? <ChapterEvaluationPanel versions={versions} evaluations={evaluations} disabled={disabled || Boolean(activeBusyAction) || !onEvaluateVersion || !onSetEvaluationBaseline || !onCompareEvaluations} onEvaluate={evaluateVersion} onSetBaseline={setEvaluationBaseline} onCompare={compareEvaluations} /> : null}
    </>;
  }

  return <aside className="review-panel review-workspace">
    <header className="review-header"><div className="review-icon"><Gauge size={18} /></div><div><span className="eyebrow">HUMAN REVIEW</span><h2>第 {draft.chapter_number ?? "—"} 章审查</h2></div><span className="review-status">待处理</span></header>
    <div className="review-tabs" role="tablist" aria-label="章节审稿工具">
      {tabs.map(({ id, icon: Icon }) => <button type="button" key={id} role="tab" aria-selected={activeTab === id} aria-controls={`review-${id}`} onClick={() => { setActionError(""); workflow.setActiveTab(id); }}><Icon size={14} />{TAB_LABELS[id]}</button>)}
    </div>
    <section id={`review-${activeTab}`} role="tabpanel" aria-label={activeLabel} className={`review-tab-panel ${activeTab === "decision" ? "has-decision-dock" : ""}`}>
      {activeTab !== "decision" && workspaceError ? <div className="error-callout" role="alert"><AlertTriangle size={16} /><span>{workspaceError}</span></div> : null}
      {activeContent}
    </section>
  </aside>;
}
