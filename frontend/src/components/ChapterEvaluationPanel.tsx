import { Flag, Gauge, GitCompareArrows, LoaderCircle, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ChapterEvaluation, ChapterVersion, EvaluationComparison } from "../types";

interface Props {
  versions: ChapterVersion[];
  evaluations: ChapterEvaluation[];
  disabled: boolean;
  onEvaluate: (versionNumber: number, includeJudge: boolean) => Promise<ChapterEvaluation>;
  onSetBaseline: (evaluationId: number) => Promise<ChapterEvaluation>;
  onCompare: (fromVersion: number, toVersion: number) => Promise<EvaluationComparison>;
}

const DIMENSION_LABELS: Record<string, string> = {
  length_adherence: "篇幅达成",
  structure: "结构完整",
  scene_coverage: "场景执行",
  narrative_coverage: "剧情回收",
  repetition_control: "重复控制",
  consistency: "一致性",
  coherence: "连贯性",
  character_consistency: "角色一致",
  prose_style: "文体质量",
  pacing: "节奏",
  scene_execution: "场景表现",
  narrative_payoff: "叙事兑现",
};

const STATUS_LABELS = {
  improved: "质量提升",
  stable: "基本持平",
  regressed: "检测到回归",
};

export function ChapterEvaluationPanel({ versions, evaluations, disabled, onEvaluate, onSetBaseline, onCompare }: Props) {
  const [versionNumber, setVersionNumber] = useState(0);
  const [includeJudge, setIncludeJudge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [comparison, setComparison] = useState<EvaluationComparison>();
  const [error, setError] = useState("");

  useEffect(() => {
    setVersionNumber(versions.at(-1)?.version_number ?? 0);
    setComparison(undefined);
    setError("");
  }, [versions]);

  const latestByVersion = useMemo(() => {
    const result = new Map<number, ChapterEvaluation>();
    for (const evaluation of evaluations) {
      if (!result.has(evaluation.version_number)) result.set(evaluation.version_number, evaluation);
    }
    return result;
  }, [evaluations]);
  const selected = latestByVersion.get(versionNumber);
  const baseline = evaluations.find((item) => item.is_baseline);
  const scores = selected ? { ...selected.deterministic_scores, ...selected.judge_scores } : {};

  async function runEvaluation() {
    if (!versionNumber) return;
    setBusy(true);
    setError("");
    setComparison(undefined);
    try {
      await onEvaluate(versionNumber, includeJudge);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "章节评测失败");
    } finally {
      setBusy(false);
    }
  }

  async function setBaseline() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await onSetBaseline(selected.id);
      setComparison(undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "设置基准失败");
    } finally {
      setBusy(false);
    }
  }

  async function compareWithBaseline() {
    if (!baseline || baseline.version_number === versionNumber) return;
    setBusy(true);
    setError("");
    try {
      setComparison(await onCompare(baseline.version_number, versionNumber));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回归比较失败");
    } finally {
      setBusy(false);
    }
  }

  if (!versions.length) return null;
  return <div className="chapter-evaluation">
    <div className="block-label"><Gauge size={14} />质量评测</div>
    <div className="evaluation-toolbar">
      <select aria-label="评测版本" value={versionNumber} onChange={(event) => { setVersionNumber(Number(event.target.value)); setComparison(undefined); }} disabled={disabled || busy}>
        {versions.map((version) => <option value={version.version_number} key={version.version_number}>v{version.version_number}</option>)}
      </select>
      <select aria-label="评测模式" value={includeJudge ? "judge" : "rules"} onChange={(event) => setIncludeJudge(event.target.value === "judge")} disabled={disabled || busy}>
        <option value="rules">规则评测</option>
        <option value="judge">规则 + 模型</option>
      </select>
      <button type="button" className="evaluation-run" title="运行质量评测" aria-label="运行质量评测" onClick={runEvaluation} disabled={disabled || busy || !versionNumber}>{busy ? <LoaderCircle className="spin" size={14} /> : includeJudge ? <Sparkles size={14} /> : <Gauge size={14} />}</button>
    </div>
    {selected ? <>
      <div className="evaluation-summary">
        <strong>{selected.overall_score.toFixed(1)}</strong>
        <div><span>综合分 / 100</span><small>{selected.judge_scores && Object.keys(selected.judge_scores).length ? `${selected.model_provider} · ${selected.model_name}` : "确定性规则"}</small></div>
        <button type="button" title={selected.is_baseline ? "当前基准" : "设为回归基准"} aria-label={selected.is_baseline ? "当前基准" : "设为回归基准"} className={selected.is_baseline ? "active" : ""} onClick={setBaseline} disabled={disabled || busy || selected.is_baseline}><Flag size={14} /></button>
      </div>
      <div className="evaluation-dimensions">{Object.entries(scores).map(([name, score]) => <div key={name}><span>{DIMENSION_LABELS[name] ?? name}</span><i><b style={{ width: `${Math.max(0, Math.min(100, score))}%` }} /></i><strong>{score.toFixed(0)}</strong></div>)}</div>
      {selected.judge_error && <p className="evaluation-warning">模型评审未完成：{selected.judge_error}</p>}
      {baseline && baseline.version_number !== versionNumber && <button type="button" className="evaluation-compare" onClick={compareWithBaseline} disabled={disabled || busy}><GitCompareArrows size={13} />与基准 v{baseline.version_number} 比较</button>}
      {comparison && <div className={`evaluation-result ${comparison.status}`}><strong>{STATUS_LABELS[comparison.status]}</strong><span>{comparison.overall_delta > 0 ? "+" : ""}{comparison.overall_delta.toFixed(1)} 分</span></div>}
      {selected.findings.length > 0 && <div className="evaluation-findings">{selected.findings.slice(0, 4).map((finding, index) => <p key={`${finding.message}-${index}`}>{finding.message}</p>)}</div>}
    </> : <p className="evaluation-empty">v{versionNumber} 尚未评测</p>}
    {error && <p className="evaluation-warning">{error}</p>}
  </div>;
}
