import { AlertTriangle, BookCheck, ListChecks, PencilLine } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import type { BookAuditReport } from "../types";

const SCORE_LABELS: Record<string, string> = {
  chapter_completion: "章节完整性",
  narrative_resolution: "剧情回收",
  character_coverage: "角色覆盖",
  timeline_integrity: "时间线",
  chapter_balance: "章节均衡",
  summary_repetition: "摘要重复",
  plot_coherence: "情节连贯",
  character_arc: "角色弧光",
  theme_payoff: "主题兑现",
  style_consistency: "风格一致",
  ending_satisfaction: "结局完成度",
  unresolved_promises: "承诺回收",
};

function ScoreGrid({ title, scores }: { title: string; scores: Record<string, number> }) {
  return <section className="book-audit-section">
    <h3>{title}</h3>
    <div className="book-audit-scores">
      {Object.entries(scores).map(([name, score]) => <div key={name}>
        <span>{SCORE_LABELS[name] || name}</span>
        <strong className={score < 60 ? "low" : score < 80 ? "medium" : ""}>{score.toFixed(1)}</strong>
      </div>)}
    </div>
  </section>;
}

interface Props {
  report: BookAuditReport;
  totalChapters: number;
  disabled?: boolean;
  onStartRevision: (chapterNumber: number, feedback: string) => Promise<void> | void;
}

export function BookAuditPanel({ report, totalChapters, disabled, onStartRevision }: Props) {
  const [chapterNumber, setChapterNumber] = useState(Math.max(totalChapters, 1));
  const [feedback, setFeedback] = useState(report.revision_priorities[0] || "");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!feedback.trim()) return;
    setSubmitting(true);
    try {
      await onStartRevision(chapterNumber, feedback.trim());
    } finally {
      setSubmitting(false);
    }
  }

  return <aside className="book-audit-panel">
    <header className="book-audit-header">
      <BookCheck size={20} />
      <div><span>FINAL MANUSCRIPT AUDIT</span><h2>全书终审</h2></div>
      <strong>{report.overall_score.toFixed(1)}</strong>
    </header>
    {(report.judge_error || report.storage_error) && <div className="book-audit-warning" role="status">
      <AlertTriangle size={15} />
      <span>{report.judge_error || report.storage_error}</span>
    </div>}
    <ScoreGrid title="结构指标" scores={report.deterministic_scores} />
    {Object.keys(report.judge_scores).length > 0 && <ScoreGrid title="文学评审" scores={report.judge_scores} />}
    {report.revision_priorities.length > 0 && <section className="book-audit-section">
      <h3><ListChecks size={14} />修订优先级</h3>
      <ol className="book-audit-priorities">
        {report.revision_priorities.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
      </ol>
    </section>}
    <section className="book-audit-section findings">
      <h3>审计发现</h3>
      {report.findings.map((finding, index) => <div className="book-audit-finding" key={`${finding.dimension}-${index}`}>
        <span>{SCORE_LABELS[finding.dimension || ""] || finding.dimension || (finding.source === "model" ? "文学评审" : "结构检查")}</span>
        {typeof finding.score === "number" && <strong>{finding.score.toFixed(1)}</strong>}
        <p>{finding.message}</p>
      </div>)}
    </section>
    <form className="book-revision-form" onSubmit={submit}>
      <h3><PencilLine size={14} />发起终稿返修</h3>
      <div>
        <label>章节
          <select value={chapterNumber} onChange={(event) => setChapterNumber(Number(event.target.value))} disabled={disabled || submitting}>
            {Array.from({ length: totalChapters }, (_, index) => index + 1).map((number) => <option key={number} value={number}>第 {number} 章</option>)}
          </select>
        </label>
        <label>返修要求
          <textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={4} maxLength={5000} disabled={disabled || submitting} />
        </label>
      </div>
      <button className="primary-button" type="submit" disabled={disabled || submitting || !feedback.trim()}>
        <PencilLine size={14} />{submitting ? "正在启动" : "开始返修"}
      </button>
    </form>
  </aside>;
}
