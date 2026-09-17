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
  onCompareVersions = async () => "",
  onEvaluateVersion,
  onSetEvaluationBaseline,
  onCompareEvaluations,
  onFocusReader,
}: ReviewWorkspaceProps) {
  const chapterNumber = draft.chapter_number ?? 0;
  const workflow = useReviewWorkflow({ novelId, chapterNumber, onSubmit });
  const [canonBusy, setCanonBusy] = useState(false);
  const pendingScene = useRef<number | undefined>(undefined);
  const activeBusyAction: ReviewBusyAction = canonBusy ? "canon" : workflow.busyAction;

  const hasIssues = issues.length > 0 || conflicts.length > 0 || Boolean(qualityReport) || Boolean(persistenceError);
  const tabs = ([
    { id: "decision" as const, icon: Check },
    ...(hasIssues ? [{ id: "issues" as const, icon: AlertTriangle }] : []),
    ...((onGenerateCandidates || candidates.length > 0) ? [{ id: "candidates" as const, icon: Sparkles }] : []),
    ...(versions.length > 0 ? [{ id: "versions" as const, icon: FileClock }] : []),
  ]);
  const activeTab = tabs.some((tab) => tab.id === workflow.activeTab) ? workflow.activeTab : "decision";
  const activeLabel = TAB_LABELS[activeTab];

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
    activeContent = <ReviewIssuesPanel issues={issues} conflicts={conflicts} qualityReport={qualityReport} persistenceError={persistenceError} disabled={disabled} busyAction={activeBusyAction} onApplyCanon={onApplyCanon ? applyCanon : undefined} onRepairFeedback={(feedback) => workflow.replaceDraft({ feedback })} />;
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
    />;
  } else if (activeTab === "versions") {
    activeContent = <>
      <VersionHistory
        versions={versions}
        disabled={disabled || Boolean(activeBusyAction)}
        onCompare={onCompareVersions}
        onRestore={async (versionNumber) => {
          pendingScene.current = workflow.sceneNumber;
          await workflow.replaceDraft({ feedback: "restore", version_number: versionNumber });
        }}
        onRestored={returnToDecision}
      />
      {onEvaluateVersion && onSetEvaluationBaseline && onCompareEvaluations ? <ChapterEvaluationPanel versions={versions} evaluations={evaluations} disabled={disabled || Boolean(activeBusyAction)} onEvaluate={onEvaluateVersion} onSetBaseline={onSetEvaluationBaseline} onCompare={onCompareEvaluations} /> : null}
    </>;
  }

  return <aside className="review-panel review-workspace">
    <header className="review-header"><div className="review-icon"><Gauge size={18} /></div><div><span className="eyebrow">HUMAN REVIEW</span><h2>第 {draft.chapter_number ?? "—"} 章审查</h2></div><span className="review-status">待处理</span></header>
    <div className="review-tabs" role="tablist" aria-label="章节审稿工具">
      {tabs.map(({ id, icon: Icon }) => <button type="button" key={id} role="tab" aria-selected={activeTab === id} aria-controls={`review-${id}`} onClick={() => workflow.setActiveTab(id)}><Icon size={14} />{TAB_LABELS[id]}</button>)}
    </div>
    <section id={`review-${activeTab}`} role="tabpanel" aria-label={activeLabel} className={`review-tab-panel ${activeTab === "decision" ? "has-decision-dock" : ""}`}>{activeContent}</section>
  </aside>;
}
