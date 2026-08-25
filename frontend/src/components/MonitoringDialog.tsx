import { Activity, CheckCircle2, CircleAlert, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getMonitoringSummary, getReadiness, listAuditLogs } from "../api";
import type { AuditLog, MonitoringSummary, ReadinessReport } from "../types";
import { useDialogLifecycle } from "../useDialogLifecycle";

interface Props {
  open: boolean;
  onClose: () => void;
}

const CHECK_LABELS: Record<string, string> = {
  sqlite: "作品数据库",
  checkpoint: "运行检查点",
  chroma: "向量记忆",
  model: "模型配置",
  schema: "数据结构",
};

const STATUS_LABELS: Record<string, string> = {
  ok: "正常",
  configured: "已配置",
  fallback: "回退模式",
  missing: "缺失",
  outdated: "需要升级",
  error: "异常",
};

function isHealthy(status: string) {
  return ["ok", "configured", "fallback"].includes(status);
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "请求失败";
}

function logTitle(log: AuditLog) {
  const path = typeof log.metadata.path === "string" ? log.metadata.path : "";
  if (log.action.startsWith("http.")) {
    return `${log.action.slice(5).toUpperCase()} ${path || "请求"}`;
  }
  return log.action;
}

function logContext(log: AuditLog) {
  if (log.resource_type || log.resource_id) {
    return `${log.resource_type || "resource"}${log.resource_id ? ` · ${log.resource_id.slice(0, 24)}` : ""}`;
  }
  if (log.actor_user_id === "user_local") return "本地工作区";
  return log.actor_user_id ? `操作人 ${log.actor_user_id.slice(0, 24)}` : "工作区操作";
}

function countStatuses(values: Record<string, number> | undefined) {
  if (!values) return null;
  return Object.values(values).reduce((total, value) => total + value, 0);
}

export function MonitoringDialog({ open, onClose }: Props) {
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [summary, setSummary] = useState<MonitoringSummary | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const { dialogRef, onBackdropMouseDown } = useDialogLifecycle<HTMLElement>(open, onClose);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const [readinessResult, auditResult, summaryResult] = await Promise.allSettled([
      getReadiness(),
      listAuditLogs(),
      getMonitoringSummary(),
    ]);

    const errors: string[] = [];
    if (readinessResult.status === "fulfilled") setReadiness(readinessResult.value);
    else errors.push(`依赖检查：${errorMessage(readinessResult.reason)}`);
    if (auditResult.status === "fulfilled") setLogs(auditResult.value.logs);
    else errors.push(`审计日志：${errorMessage(auditResult.reason)}`);
    if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
    else errors.push(`运行聚合：${errorMessage(summaryResult.reason)}`);

    setError(errors.join("；"));
    setLoaded(true);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [load, open]);

  if (!open) return null;
  const readinessLabel = !readiness ? "检查中" : readiness.status === "ready" ? "已就绪" : "未就绪";
  const runCount = countStatuses(summary?.run_jobs);
  const transferCount = countStatuses(summary?.transfer_jobs);

  return (
    <div className="model-settings-backdrop" onMouseDown={onBackdropMouseDown}>
      <section ref={dialogRef} tabIndex={-1} className="model-settings-dialog monitoring-dialog" role="dialog" aria-modal="true" aria-labelledby="monitoring-title">
        <header className="model-settings-header">
          <div><span className="eyebrow">OPERATIONS</span><h2 id="monitoring-title">运行状态与审计</h2></div>
          <div className="model-settings-header-actions">
            <button type="button" className="dialog-close-button" aria-label="刷新运行状态" title="刷新" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} size={17} /></button>
            <button type="button" className="dialog-close-button" aria-label="关闭运行状态" title="关闭" disabled={loading} onClick={onClose}><X size={18} /></button>
          </div>
        </header>
        {error && <p className="monitoring-error"><CircleAlert size={14} />{error}</p>}

        <div className="monitoring-section">
          <div className="monitoring-heading"><ShieldCheck size={15} /><strong>依赖就绪</strong><span className={readiness?.status === "ready" ? "passed" : "attention"}>{readinessLabel}</span></div>
          <div className="monitoring-checks">
            {Object.entries(readiness?.checks ?? {}).map(([name, check]) => (
              <div key={name}>
                <span>{CHECK_LABELS[name] ?? name}</span>
                <strong className={isHealthy(check.status) ? "ok" : "bad"}>{isHealthy(check.status) ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}{STATUS_LABELS[check.status] ?? check.status}</strong>
              </div>
            ))}
            {!readiness && <div className="monitoring-placeholder">正在检查关键依赖...</div>}
          </div>
        </div>

        <div className="monitoring-section">
          <div className="monitoring-heading"><Activity size={15} /><strong>运行聚合</strong><small>当前工作区</small></div>
          <div className="monitoring-summary">
            <div><span>创作任务</span><strong>{runCount ?? "—"}</strong><small>{summary ? `${summary.run_jobs.failed ?? 0} 失败` : "等待数据"}</small></div>
            <div><span>传输任务</span><strong>{transferCount ?? "—"}</strong><small>{summary ? `${summary.transfer_jobs.failed ?? 0} 失败` : "等待数据"}</small></div>
            <div><span>模型调用</span><strong>{summary?.model_calls.total ?? "—"}</strong><small>{summary ? `${summary.model_calls.failed ?? 0} 失败` : "等待数据"}</small></div>
            <div><span>模型耗时</span><strong>{summary ? `${Math.round(summary.model_calls.duration_ms / 1000)}s` : "—"}</strong><small>{summary ? `${summary.model_calls.input_tokens + summary.model_calls.output_tokens} tokens` : "等待数据"}</small></div>
          </div>
        </div>

        <div className="monitoring-section monitoring-log-section">
          <div className="monitoring-heading"><Activity size={15} /><strong>最近操作</strong><small>{loaded ? `${logs.length} 条` : "读取中"}</small></div>
          <div className="monitoring-logs">
            {logs.map((log) => <div className="monitoring-log" key={log.id}><strong>{logTitle(log)}</strong><time>{new Date(log.created_at).toLocaleString("zh-CN", { hour12: false })}</time><small>{logContext(log)}</small></div>)}
            {logs.length === 0 && <div className="monitoring-empty">{loading || !loaded ? "正在读取审计记录..." : "尚无审计记录"}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
