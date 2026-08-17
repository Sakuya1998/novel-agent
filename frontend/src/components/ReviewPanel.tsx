import { AlertTriangle, Check, MessageSquareText, Send } from "lucide-react";
import { useState } from "react";
import type { ConsistencyIssue, Draft } from "../types";

interface Props { draft: Draft; issues: ConsistencyIssue[]; persistenceError: string; disabled: boolean; onSubmit: (feedback: string) => Promise<void>; }

export function ReviewPanel({ draft, issues, persistenceError, disabled, onSubmit }: Props) {
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit(value: string) { setSubmitting(true); try { await onSubmit(value); setFeedback(""); } finally { setSubmitting(false); } }
  return <aside className="review-panel">
    <div className="review-header"><div className="review-icon"><MessageSquareText size={18} /></div><div><span className="eyebrow">HUMAN REVIEW</span><h2>第 {draft.chapter_number ?? "—"} 章审查</h2></div><span className="review-status">待处理</span></div>
    {persistenceError && <div className="error-callout"><AlertTriangle size={16} /><span>{persistenceError}</span></div>}
    {issues.length > 0 && <div className="issue-block"><div className="block-label"><AlertTriangle size={14} />一致性检查</div>{issues.map((issue, index) => <div className="issue" key={`${issue.description}-${index}`}><span className={`severity ${issue.severity || "low"}`}>{issue.severity || "low"}</span><p>{issue.description || "未提供描述"}</p></div>)}</div>}
    <div className="review-form"><label htmlFor="feedback">审查意见</label><textarea id="feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="留空并通过，或写下需要重写的方向……" disabled={disabled || submitting} rows={7} /><div className="review-actions"><button className="secondary-button" onClick={() => submit(feedback)} disabled={disabled || submitting}><Send size={14} />提交意见</button><button className="primary-button" onClick={() => submit("approve")} disabled={disabled || submitting}><Check size={15} />通过定稿</button></div></div>
  </aside>;
}
