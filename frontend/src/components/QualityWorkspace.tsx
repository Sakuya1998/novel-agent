import { Activity, ArrowUpRight, FlaskConical, Gauge, ShieldCheck } from "lucide-react";
import type { WorkbenchState } from "../types";

interface Props {
  state: WorkbenchState;
  onOpenMonitoring: () => void;
  onOpenBenchmarks: () => void;
  onOpenTraces: () => void;
}

export function QualityWorkspace({ state, onOpenMonitoring, onOpenBenchmarks, onOpenTraces }: Props) {
  const report = state.quality_report;
  const usage = state.model_usage;

  return (
    <section className="workspace-view quality-workspace" aria-labelledby="quality-view-title">
      <header className="workspace-view-header">
        <div><span className="section-label">QUALITY CONTROL</span><h2 id="quality-view-title">质量与运行</h2></div>
        <span>{state.issues.length} 个待处理问题</span>
      </header>

      <div className="quality-summary">
        <div><span>当前质量分</span><strong>{report ? report.overall_score.toFixed(1) : "--"}</strong><small>{report ? `门槛 ${report.threshold.toFixed(1)}` : "尚未评测"}</small></div>
        <div><span>模型调用</span><strong>{usage.successful_calls}</strong><small>{usage.failed_attempts} 次失败</small></div>
        <div><span>累计 Tokens</span><strong>{new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(usage.total_tokens)}</strong><small>{usage.fallback_attempts} 次降级</small></div>
      </div>

      <div className="quality-action-list">
        <button type="button" onClick={onOpenMonitoring}><ShieldCheck size={17} /><span><strong>运行与审计</strong><small>服务、后台任务和审计日志</small></span><ArrowUpRight size={16} /></button>
        <button type="button" onClick={onOpenBenchmarks}><FlaskConical size={17} /><span><strong>质量基准</strong><small>运行并比较回归评测</small></span><ArrowUpRight size={16} /></button>
        <button type="button" onClick={onOpenTraces}><Activity size={17} /><span><strong>模型调用轨迹</strong><small>查看当前作品的调用明细</small></span><ArrowUpRight size={16} /></button>
      </div>

      {report?.findings?.length ? <section className="quality-findings">
        <div className="planning-summary-heading"><Gauge size={16} /><strong>最近发现</strong></div>
        {report.findings.slice(0, 6).map((finding) => <article key={finding.dimension}><strong>{finding.dimension}</strong><span>{finding.score.toFixed(1)}</span><p>{finding.message}</p></article>)}
      </section> : null}
    </section>
  );
}
