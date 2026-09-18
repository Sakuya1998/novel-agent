import { AlertTriangle, Gauge } from "lucide-react";
import { useState } from "react";
import type { CanonOperation, ConflictExplanation, ConsistencyIssue, QualityGateReport } from "../types";
import type { ReviewBusyAction } from "../useReviewWorkflow";

interface Props {
  issues: ConsistencyIssue[];
  conflicts?: ConflictExplanation[];
  qualityReport?: QualityGateReport;
  persistenceError?: string;
  disabled: boolean;
  busyAction: ReviewBusyAction;
  onApplyCanon?: (operation: CanonOperation) => Promise<void>;
  onRepairFeedback?: (feedback: string) => Promise<void>;
  onError?: (reason: unknown) => void;
}

function legacyConflicts(issues: ConsistencyIssue[]): ConflictExplanation[] {
  return issues.map((issue, index) => ({
    conflict_id: `legacy-${index}`,
    type: issue.type ?? "consistency",
    title: issue.description ?? "一致性问题",
    severity: issue.severity ?? "low",
    description: issue.description ?? "未提供描述",
    evidence: [],
    conflicting_records: [],
    impact: "",
    repair_options: issue.suggestion
      ? [{ id: "legacy", label: "按建议返修", kind: "revision_feedback", feedback: issue.suggestion }]
      : [],
  }));
}

export function ReviewIssuesPanel({
  issues,
  conflicts = [],
  qualityReport,
  persistenceError = "",
  disabled,
  busyAction,
  onApplyCanon,
  onRepairFeedback,
  onError,
}: Props) {
  const [expandedConflict, setExpandedConflict] = useState<string>();
  const displayedConflicts = conflicts.length ? conflicts : legacyConflicts(issues);
  const controlsDisabled = disabled || Boolean(busyAction);

  async function applyRepair(option: ConflictExplanation["repair_options"][number]) {
    try {
      if (option.kind === "canon_operation" && option.operation && onApplyCanon) {
        await onApplyCanon(option.operation);
        return;
      }
      if (option.kind === "revision_feedback" && option.feedback && onRepairFeedback) {
        await onRepairFeedback(option.feedback);
      }
    } catch (reason) {
      onError?.(reason);
    }
  }

  return <div className="review-issues-panel">
    {persistenceError ? <div className="error-callout" role="alert"><AlertTriangle size={16} /><span>{persistenceError}</span></div> : null}
    {(displayedConflicts.length > 0) ? <div className="issue-block">
      <div className="block-label"><AlertTriangle size={14} />一致性检查</div>
      {displayedConflicts.map((conflict) => <div className="issue" key={conflict.conflict_id}>
        <span className={`severity ${conflict.severity || "low"}`}>{conflict.severity || "low"}</span>
        <div>
          <p>{conflict.description || conflict.title}</p>
          <button type="button" className="issue-detail-toggle" onClick={() => setExpandedConflict((current) => current === conflict.conflict_id ? undefined : conflict.conflict_id)}>
            {expandedConflict === conflict.conflict_id ? "收起详情" : "查看证据与建议"}
          </button>
          {expandedConflict === conflict.conflict_id ? <div className="issue-detail">
            {conflict.impact ? <p className="issue-impact">{conflict.impact}</p> : null}
            {conflict.evidence.length > 0 ? <div className="issue-evidence">{conflict.evidence.map((item, index) => <div key={`${item.label}-${index}`}><strong>{item.label}</strong><span>{typeof item.value === "string" ? item.value : JSON.stringify(item.value)}</span></div>)}</div> : null}
            <div className="issue-repair-actions">{conflict.repair_options.map((option) => <button type="button" className="secondary-button" key={option.id} disabled={controlsDisabled} onClick={() => void applyRepair(option)}>
              {busyAction === "canon" && option.kind === "canon_operation" ? "处理中…" : busyAction === "revision" && option.kind === "revision_feedback" ? "处理中…" : option.label}
            </button>)}</div>
          </div> : null}
        </div>
      </div>)}
    </div> : null}
    {qualityReport ? <div className="quality-gate-block">
      <div className="block-label"><Gauge size={14} />自动质量门</div>
      <div className={`quality-gate-score ${qualityReport.passed ? "passed" : "attention"}`}><strong>{qualityReport.overall_score.toFixed(1)}</strong><span>/ {qualityReport.threshold.toFixed(1)}</span><em>{qualityReport.passed ? "通过" : qualityReport.status === "escalated" ? "转人工" : "待改进"}</em></div>
      {qualityReport.findings?.filter((item) => item.score < qualityReport.threshold).slice(0, 3).map((item) => <p className="quality-gate-finding" key={item.dimension}><strong>{item.dimension}</strong><span>{item.score.toFixed(1)} 分 · {item.message}</span></p>)}
    </div> : null}
  </div>;
}
