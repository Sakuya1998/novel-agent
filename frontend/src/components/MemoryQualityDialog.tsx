import { AlertTriangle, BrainCircuit, CheckCircle2, Database, Gauge, RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { MemoryQualityHistory, MemoryQualityReport } from "../types";

interface Props {
  open: boolean;
  history: MemoryQualityHistory;
  onClose: () => void;
  onRefresh: () => Promise<MemoryQualityHistory>;
  onEvaluate: (k?: number) => Promise<unknown>;
  onRebuild: (evaluate?: boolean, k?: number) => Promise<unknown>;
}

function reportOf(history: MemoryQualityHistory): MemoryQualityReport | null {
  const report = history.latest?.report;
  if (!report) return null;
  return report.quality ?? report;
}

function percent(value: number | undefined): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}

export function MemoryQualityDialog({ open, history, onClose, onRefresh, onEvaluate, onRebuild }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const report = reportOf(history);

  useEffect(() => {
    if (open) void onRefresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "无法读取记忆质量"));
  }, [onRefresh, open]);

  if (!open) return null;
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : "记忆操作失败"); } finally { setBusy(false); }
  }

  return <section className="model-settings-dialog memory-quality-dialog" role="dialog" aria-modal="true" aria-labelledby="memory-quality-title">
    <div className="memory-quality-header"><div className="dialog-title"><BrainCircuit size={18} /><div><span className="eyebrow">MEMORY QUALITY</span><h2 id="memory-quality-title">长期记忆质量</h2></div></div><button type="button" className="icon-button" title="关闭" aria-label="关闭" onClick={onClose}><X size={16} /></button></div>
    <div className="memory-quality-toolbar"><button type="button" className="secondary-button" disabled={busy} onClick={() => void run(() => onEvaluate(5))}><Gauge size={14} />运行检索评测</button><button type="button" className="primary-button" disabled={busy} onClick={() => void run(() => onRebuild(true, 5))}><RefreshCw size={14} />重建并评测索引</button></div>
    {error && <div className="memory-quality-error"><AlertTriangle size={14} />{error}</div>}
    {!report ? <div className="memory-quality-empty"><Database size={22} /><strong>尚无记忆质量记录</strong><span>运行一次评测即可建立基线。</span></div> : <>
      <div className="memory-quality-status"><span className={report.status === "passed" ? "passed" : report.status === "unavailable" ? "unavailable" : "attention"}>{report.status === "passed" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{report.status === "passed" ? "质量门通过" : report.status === "unavailable" ? "向量索引不可用" : "需要关注"}</span><small>{history.latest?.mode === "rebuild" ? "最近一次为重建" : "最近一次为评测"}</small></div>
      <div className="memory-quality-metrics"><div><span>Recall@{report.k ?? 5}</span><strong>{percent(report.recall_at_k)}</strong></div><div><span>MRR</span><strong>{(report.mrr ?? 0).toFixed(2)}</strong></div><div><span>索引记录</span><strong>{report.index_record_count ?? 0}</strong></div><div><span>过期命中率</span><strong>{percent(report.stale_fact_hit_rate)}</strong></div><div><span>Canon 冲突风险</span><strong>{percent(report.canon_vector_conflict_rate)}</strong></div><div><span>样本通过</span><strong>{report.passed_cases ?? 0}/{report.case_count ?? 0}</strong></div></div>
      {report.errors?.length ? <div className="memory-quality-error"><AlertTriangle size={14} />{report.errors[0]}</div> : null}
      <div className="memory-quality-history"><div className="block-label">最近运行</div>{history.runs.slice(0, 5).map((run) => <div className="memory-quality-run" key={run.id}><span>{run.mode === "rebuild" ? "重建" : "评测"}</span><strong>{run.report?.quality?.recall_at_k !== undefined ? percent(run.report.quality.recall_at_k) : run.report?.recall_at_k !== undefined ? percent(run.report.recall_at_k) : "—"}</strong><small>{new Date(run.created_at).toLocaleString()}</small></div>)}</div>
    </>}
  </section>;
}
