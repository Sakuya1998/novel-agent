import { AlertTriangle, CheckCircle2, FlaskConical, LoaderCircle, Play, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { EvaluationBenchmarkRun } from "../types";

interface Props {
  open: boolean;
  runs: EvaluationBenchmarkRun[];
  onRun: (includeJudge: boolean, baselineRunId?: string) => Promise<EvaluationBenchmarkRun>;
  onClose: () => void;
}

export function EvaluationBenchmarkDialog({ open, runs, onRun, onClose }: Props) {
  const [includeJudge, setIncludeJudge] = useState(false);
  const [baselineRunId, setBaselineRunId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const selected = useMemo(
    () => runs.find((run) => run.id === selectedId) ?? runs[0],
    [runs, selectedId],
  );

  async function execute() {
    setLoading(true);
    setError("");
    try {
      const result = await onRun(includeJudge, baselineRunId);
      setSelectedId(result.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "评测运行失败");
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;
  return <div className="model-settings-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="model-settings-dialog evaluation-benchmark-dialog" role="dialog" aria-modal="true" aria-labelledby="evaluation-benchmark-title">
      <header className="model-settings-header">
        <div><span className="eyebrow">REGRESSION EVALS</span><h2 id="evaluation-benchmark-title">质量评测基准</h2></div>
        <button className="dialog-close-button" type="button" title="关闭" aria-label="关闭质量评测基准" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="evaluation-benchmark-toolbar">
        <label className="benchmark-toggle"><input type="checkbox" checked={includeJudge} onChange={(event) => setIncludeJudge(event.target.checked)} disabled={loading} /><span>启用模型评审</span></label>
        <label>比较基准<select aria-label="选择评测基准" value={baselineRunId} onChange={(event) => setBaselineRunId(event.target.value)} disabled={loading}><option value="">仅执行绝对门禁</option>{runs.map((run) => <option value={run.id} key={run.id}>{run.created_at.slice(0, 19).replace("T", " ")} · {run.overall_score.toFixed(1)}</option>)}</select></label>
        <button type="button" className="primary-button" onClick={() => void execute()} disabled={loading}>{loading ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}运行评测</button>
      </div>
      {error && <div className="model-trace-error"><AlertTriangle size={14} />{error}</div>}
      <div className="evaluation-benchmark-layout">
        <aside className="evaluation-run-list">
          {runs.map((run) => <button type="button" className={run.id === selected?.id ? "active" : ""} key={run.id} onClick={() => setSelectedId(run.id)}><span className={run.status}>{run.status === "passed" ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}{run.overall_score.toFixed(1)}</span><small>{run.created_at.slice(0, 19).replace("T", " ")}</small></button>)}
          {!runs.length && <div className="evaluation-run-empty"><FlaskConical size={18} />尚无评测运行</div>}
        </aside>
        <div className="evaluation-case-list">
          {selected && <>
            <div className="evaluation-run-summary"><div><strong>{selected.overall_score.toFixed(1)}</strong><span>/ 100</span></div><p><b>{selected.status === "passed" ? "门禁通过" : "存在质量回归"}</b><small>{selected.include_judge && selected.model_name ? `${selected.model_provider} · ${selected.model_name}` : "确定性评测"}</small></p><code title={selected.input_hash}>{selected.input_hash.slice(0, 12)}</code></div>
            {selected.judge_error && <div className="evaluation-judge-warning"><AlertTriangle size={13} />模型评审不可用，已保留确定性结果：{selected.judge_error}</div>}
            {selected.cases.map((item) => <div className={`evaluation-case-row ${item.passed ? "passed" : "failed"}`} key={item.id}><span>{item.passed ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{item.title}</strong><small>{item.category.replaceAll("_", " ")}</small></div><em>{item.overall_score.toFixed(1)}</em><p>{item.baseline_delta === null ? `门槛 ${item.minimum_score.toFixed(1)}` : `较基准 ${item.baseline_delta > 0 ? "+" : ""}${item.baseline_delta.toFixed(1)}`}</p></div>)}
          </>}
        </div>
      </div>
      <footer className="model-trace-footer">固定样本覆盖短章、跨章一致性、角色弧光、叙事线程和风格；Prompt 与输入仅保存 SHA-256 哈希。</footer>
    </section>
  </div>;
}
