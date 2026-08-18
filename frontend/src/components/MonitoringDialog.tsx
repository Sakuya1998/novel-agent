import { Activity, CheckCircle2, CircleAlert, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { getMonitoringSummary, getReadiness, listAuditLogs } from "../api";
import type { AuditLog, MonitoringSummary, ReadinessReport } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MonitoringDialog({ open, onClose }: Props) {
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [summary, setSummary] = useState<MonitoringSummary | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    void Promise.all([getReadiness(), listAuditLogs(), getMonitoringSummary()]).then(([status, audit, runtime]) => {
      setReadiness(status);
      setLogs(audit.logs);
      setSummary(runtime);
    }).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "无法读取运行状态");
    });
  }, [open]);

  if (!open) return null;
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="model-settings-dialog monitoring-dialog" role="dialog" aria-modal="true" aria-labelledby="monitoring-title">
      <header className="model-settings-header"><div><span className="eyebrow">OPERATIONS</span><h2 id="monitoring-title">运行状态与审计</h2></div><button type="button" className="dialog-close-button" aria-label="关闭运行状态" title="关闭" onClick={onClose}><X size={18} /></button></header>
      {error && <p className="auth-error">{error}</p>}
      <div className="monitoring-section"><div className="monitoring-heading"><ShieldCheck size={15} /><strong>依赖就绪</strong><span className={readiness?.status === "ready" ? "passed" : "attention"}>{readiness?.status === "ready" ? "已就绪" : "检查中"}</span></div><div className="monitoring-checks">{Object.entries(readiness?.checks ?? {}).map(([name, check]) => <div key={name}><span>{name}</span><strong className={check.status === "ok" || check.status === "configured" || check.status === "fallback" ? "ok" : "bad"}>{check.status === "ok" || check.status === "configured" || check.status === "fallback" ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}{check.status}</strong></div>)}</div></div>
      <div className="monitoring-section"><div className="monitoring-heading"><Activity size={15} /><strong>运行聚合</strong><small>当前工作区</small></div><div className="monitoring-summary"><div><span>创作任务</span><strong>{Object.values(summary?.run_jobs ?? {}).reduce((total, value) => total + value, 0)}</strong><small>{summary?.run_jobs.failed ?? 0} 失败</small></div><div><span>传输任务</span><strong>{Object.values(summary?.transfer_jobs ?? {}).reduce((total, value) => total + value, 0)}</strong><small>{summary?.transfer_jobs.failed ?? 0} 失败</small></div><div><span>模型调用</span><strong>{summary?.model_calls.total ?? 0}</strong><small>{summary?.model_calls.failed ?? 0} 失败</small></div><div><span>模型耗时</span><strong>{Math.round((summary?.model_calls.duration_ms ?? 0) / 1000)}s</strong><small>{(summary?.model_calls.input_tokens ?? 0) + (summary?.model_calls.output_tokens ?? 0)} tokens</small></div></div></div>
      <div className="monitoring-section"><div className="monitoring-heading"><Activity size={15} /><strong>最近操作</strong><small>{logs.length} 条</small></div><div className="monitoring-logs">{logs.map((log) => <div className="monitoring-log" key={log.id}><strong>{log.action}</strong><span>{log.created_at.slice(0, 19).replace("T", " ")}</span><small>{log.resource_type || "request"}{log.resource_id ? ` · ${log.resource_id.slice(0, 18)}` : ""}</small></div>)}{logs.length === 0 && <div className="monitoring-empty">尚无审计记录</div>}</div></div>
    </section>
  </div>;
}
