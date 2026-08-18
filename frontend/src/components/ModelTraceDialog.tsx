import { Activity, AlertTriangle, CheckCircle2, RefreshCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ModelTrace } from "../types";

interface Props {
  open: boolean;
  traces: ModelTrace[];
  onRefresh: (agent?: string) => Promise<ModelTrace[]>;
  onClose: () => void;
}

function shortHash(value: string): string {
  return value ? value.slice(0, 10) : "-";
}

export function ModelTraceDialog({ open, traces, onRefresh, onClose }: Props) {
  const [agent, setAgent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const agents = useMemo(
    () => Array.from(new Set(traces.map((trace) => trace.agent))).sort(),
    [traces],
  );

  async function refresh(nextAgent = agent) {
    setLoading(true);
    setError("");
    try {
      await onRefresh(nextAgent);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法加载调用轨迹");
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;
  return <div className="model-settings-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="model-settings-dialog model-trace-dialog" role="dialog" aria-modal="true" aria-labelledby="model-trace-title">
      <header className="model-settings-header">
        <div><span className="eyebrow">AGENT TRACE</span><h2 id="model-trace-title">模型调用轨迹</h2></div>
        <div className="model-settings-header-actions"><span className="model-source-badge database">最近 {traces.length} 条</span><button className="dialog-close-button" type="button" title="关闭" aria-label="关闭模型调用轨迹" onClick={onClose}><X size={18} /></button></div>
      </header>
      <div className="model-trace-toolbar">
        <label>Agent<select aria-label="筛选 Agent" value={agent} onChange={(event) => { const value = event.target.value; setAgent(value); void refresh(value); }} disabled={loading}><option value="">全部 Agent</option>{agents.map((name) => <option value={name} key={name}>{name}</option>)}</select></label>
        <button type="button" className="secondary-button" onClick={() => refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={14} />刷新</button>
      </div>
      {error && <div className="model-trace-error"><AlertTriangle size={14} />{error}</div>}
      <div className="model-trace-table">
        <div className="model-trace-head"><span>Agent / 状态</span><span>模型</span><span>输入 / 输出</span><span>耗时</span><span>哈希</span></div>
        {traces.map((trace) => <div className={`model-trace-row ${trace.success ? "success" : "failed"}`} key={trace.id}>
          <div>{trace.success ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}<span><strong>{trace.agent}</strong><small>{trace.success ? "成功" : trace.error_type || "失败"}{trace.fallback_used ? " · 备用路由" : ""}</small></span></div>
          <span><strong>{trace.model_name}</strong><small>{trace.provider} · {trace.purpose} · 尝试 {trace.attempt}</small></span>
          <span><strong>{trace.input_tokens} / {trace.output_tokens}</strong><small>{trace.input_chars} / {trace.output_chars} 字符{trace.usage_estimated ? " · 估算" : ""}</small></span>
          <span><strong>{trace.duration_ms} ms</strong><small>{trace.created_at.slice(0, 19).replace("T", " ")}</small></span>
          <span className="model-trace-hash"><code title={trace.input_hash}>I {shortHash(trace.input_hash)}</code><code title={trace.output_hash}>O {shortHash(trace.output_hash)}</code></span>
        </div>)}
        {!loading && traces.length === 0 && <div className="model-trace-empty"><Activity size={18} />尚无模型调用记录</div>}
      </div>
      <footer className="model-trace-footer">调用轨迹只保存哈希和统计元数据，不保存 Prompt、正文或 API Key。</footer>
    </section>
  </div>;
}
