import { AlertTriangle, Check, FileClock, Gauge, Sparkles } from "lucide-react";
import { useRef } from "react";
import type { CanonOperation, ChapterCandidate, ChapterEvaluation, ChapterVersion, ConflictExplanation, ConsistencyIssue, Draft, EvaluationComparison, QualityGateReport } from "../types";
import type { ReviewTab, ReviewWorkflow } from "../useReviewWorkflow";
import { ChapterCandidatesPanel } from "./ChapterCandidatesPanel";
import { ChapterEvaluationPanel } from "./ChapterEvaluationPanel";
import { ReviewDecisionPanel } from "./ReviewDecisionPanel";
import { ReviewIssuesPanel } from "./ReviewIssuesPanel";
import { VersionHistory } from "./VersionHistory";

export interface ReviewWorkspaceProps {
  workflow: ReviewWorkflow;
  draft: Draft;
  issues: ConsistencyIssue[];
  conflicts?: ConflictExplanation[];
  qualityReport?: QualityGateReport;
  persistenceError: string;
  versions?: ChapterVersion[];
  evaluations?: ChapterEvaluation[];
  candidates?: ChapterCandidate[];
  disabled: boolean;
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
  workflow,
  draft,
  issues,
  conflicts = [],
  qualityReport,
  persistenceError,
  versions = [],
  evaluations = [],
  candidates = [],
  disabled,
  onApplyCanon,
  onGenerateCandidates,
  onCompareVersions,
  onEvaluateVersion,
  onSetEvaluationBaseline,
  onCompareEvaluations,
  onFocusReader,
}: ReviewWorkspaceProps) {
  const tabRefs = useRef(new Map<ReviewTab, HTMLButtonElement>());
  const activeBusyAction = workflow.busyAction;

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
  const workspaceError = workflow.error;
  const compareVersions = onCompareVersions ?? (async () => "");
  const evaluateVersion = onEvaluateVersion ?? (async () => { throw new Error("章节评测不可用"); });
  const setEvaluationBaseline = onSetEvaluationBaseline ?? (async () => { throw new Error("设置基准不可用"); });
  const compareEvaluations = onCompareEvaluations ?? (async () => { throw new Error("回归比较不可用"); });

  function returnToDecision() {
    workflow.setActiveTab("decision");
    onFocusReader?.(undefined, workflow.focusRequest + 1);
  }

  const decisionContent = <div className="review-decision-dock">
    <ReviewDecisionPanel
      scenePlan={draft.scene_plan ?? []}
      sceneNumber={workflow.sceneNumber}
      feedback={workflow.feedback}
      busyAction={activeBusyAction}
      disabled={disabled}
      error={workflow.error}
      onSceneChange={(sceneNumber) => {
        workflow.selectScene(sceneNumber);
        onFocusReader?.(sceneNumber, workflow.focusRequest + 1);
      }}
      onFeedbackChange={workflow.setFeedback}
      onRevise={workflow.submitRevision}
      onApprove={workflow.approve}
    />
  </div>;

  let activeContent: React.ReactNode = decisionContent;
  if (activeTab === "issues") {
    activeContent = <ReviewIssuesPanel issues={issues} conflicts={conflicts} qualityReport={qualityReport} persistenceError={persistenceError} disabled={disabled} busyAction={activeBusyAction} onApplyCanon={onApplyCanon ? (operation) => workflow.runAction("canon", () => onApplyCanon(operation)) : undefined} onRepairFeedback={(feedback) => workflow.replaceDraft({ feedback })} />;
  } else if (activeTab === "candidates") {
    activeContent = <ChapterCandidatesPanel
      candidates={candidates}
      currentContent={draft.content ?? ""}
      disabled={disabled || Boolean(activeBusyAction)}
      onGenerate={onGenerateCandidates ? (count, instruction) => workflow.runAction("generate", () => onGenerateCandidates(count, instruction)) : undefined}
      onSelect={(candidateId) => workflow.replaceDraft({ feedback: "candidate", candidate_id: candidateId }, returnToDecision)}
    />;
  } else if (activeTab === "versions") {
    activeContent = <>
      {versions.length > 0 ? <VersionHistory
          versions={versions}
          disabled={disabled || Boolean(activeBusyAction)}
          onCompare={compareVersions}
          onRestore={(versionNumber) => workflow.replaceDraft({ feedback: "restore", version_number: versionNumber }, returnToDecision)}
        /> : <div className="review-empty-state">暂无可用版本</div>}
      {hasEvaluationSurface ? <ChapterEvaluationPanel versions={versions} evaluations={evaluations} disabled={disabled || Boolean(activeBusyAction) || !onEvaluateVersion || !onSetEvaluationBaseline || !onCompareEvaluations} onEvaluate={evaluateVersion} onSetBaseline={setEvaluationBaseline} onCompare={compareEvaluations} /> : null}
    </>;
  }

  return <aside className="review-panel review-workspace">
    <header className="review-header"><div className="review-icon"><Gauge size={18} /></div><div><span className="eyebrow">HUMAN REVIEW</span><h2>第 {draft.chapter_number ?? "—"} 章审查</h2></div><span className="review-status">待处理</span></header>
    <div className="review-tabs" role="tablist" aria-label="章节审稿工具">
      {tabs.map(({ id, icon: Icon }, index) => <button type="button" key={id} role="tab"
        ref={(element) => { if (element) tabRefs.current.set(id, element); else tabRefs.current.delete(id); }}
        tabIndex={activeTab === id ? 0 : -1} aria-selected={activeTab === id} aria-controls={`review-${id}`}
        onClick={() => workflow.setActiveTab(id)}
        onKeyDown={(event) => {
          let next: number;
          if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
          else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = tabs.length - 1;
          else return;
          event.preventDefault();
          workflow.setActiveTab(tabs[next].id);
          tabRefs.current.get(tabs[next].id)?.focus();
        }}><Icon size={14} />{TAB_LABELS[id]}</button>)}
    </div>
    <section id={`review-${activeTab}`} role="tabpanel" aria-label={activeLabel} className={`review-tab-panel ${activeTab === "decision" ? "has-decision-dock" : ""}`}>
      {activeTab !== "decision" && workspaceError ? <div className="error-callout" role="alert"><AlertTriangle size={16} /><span>{workspaceError}</span></div> : null}
      {activeContent}
    </section>
  </aside>;
}
