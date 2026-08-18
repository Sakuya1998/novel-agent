import { Check, GitCompareArrows, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChapterCandidate } from "../types";

const SCORE_LABELS: Record<string, string> = {
  length_adherence: "篇幅",
  structure: "结构",
  scene_coverage: "场景",
  narrative_coverage: "剧情",
  repetition_control: "重复",
  consistency: "一致性",
};

interface Props {
  candidates: ChapterCandidate[];
  currentContent: string;
  disabled: boolean;
  onGenerate: (count: number, instruction: string) => Promise<void>;
  onSelect: (candidateId: string) => Promise<void>;
}

export function ChapterCandidatesPanel({ candidates, currentContent, disabled, onGenerate, onSelect }: Props) {
  const [count, setCount] = useState(3);
  const [instruction, setInstruction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectingId, setSelectingId] = useState("");
  const [compareId, setCompareId] = useState("");
  const compared = useMemo(
    () => candidates.find((candidate) => candidate.id === compareId),
    [candidates, compareId],
  );

  async function generate() {
    setSubmitting(true);
    try {
      await onGenerate(count, instruction.trim());
    } finally {
      setSubmitting(false);
    }
  }

  async function select(candidateId: string) {
    setSelectingId(candidateId);
    try {
      await onSelect(candidateId);
    } finally {
      setSelectingId("");
    }
  }

  return <section className="candidate-panel">
    <div className="block-label"><Sparkles size={14} />候选稿探索</div>
    <div className="candidate-generator">
      <div className="candidate-count" aria-label="候选稿数量">
        {[2, 3, 4].map((value) => <button
          type="button"
          key={value}
          className={count === value ? "active" : ""}
          aria-pressed={count === value}
          onClick={() => setCount(value)}
          disabled={disabled || submitting}
        >{value} 稿</button>)}
      </div>
      <textarea
        aria-label="候选稿创作方向"
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        placeholder="可选：例如强化人物冲突，同时保留结尾揭示"
        rows={3}
        maxLength={5000}
        disabled={disabled || submitting}
      />
      <button type="button" className="secondary-button" onClick={generate} disabled={disabled || submitting}>
        <Sparkles size={14} />{submitting ? "正在启动" : "生成候选稿"}
      </button>
    </div>

    {candidates.length > 0 && <div className="candidate-list">
      {candidates.map((candidate) => <article className={`candidate-card ${candidate.status}`} key={candidate.id}>
        <header>
          <div><span>方案 {candidate.candidate_number}</span><strong>{candidate.overall_score.toFixed(1)}</strong></div>
          {candidate.status === "selected" && <em><Check size={12} />已选择</em>}
          {candidate.status === "stale" && <em className="stale-label">已过期</em>}
        </header>
        <p>{candidate.preview || candidate.content.slice(0, 240)}</p>
        <div className="candidate-scores">
          {Object.entries(candidate.scores).map(([name, score]) => <span key={name}>
            {SCORE_LABELS[name] || name}<strong>{score.toFixed(0)}</strong>
          </span>)}
        </div>
        <div className="candidate-actions">
          <button type="button" className="icon-text-button" onClick={() => setCompareId(candidate.id)} disabled={disabled || submitting || Boolean(selectingId)}>
            <GitCompareArrows size={14} />对比
          </button>
          <button type="button" className="primary-button" onClick={() => select(candidate.id)} disabled={disabled || submitting || Boolean(selectingId) || candidate.status === "stale"}>
            <Check size={14} />{candidate.status === "stale" ? "需重新生成" : selectingId === candidate.id ? "正在采用" : "采用此稿"}
          </button>
        </div>
      </article>)}
    </div>}

    {compared && <div className="candidate-compare" role="dialog" aria-label="候选稿对比">
      <header><strong>当前稿与方案 {compared.candidate_number}</strong><button type="button" className="icon-button" aria-label="关闭候选稿对比" onClick={() => setCompareId("")}><X size={15} /></button></header>
      <div><article><span>当前稿</span><p>{currentContent}</p></article><article><span>候选稿 · {compared.overall_score.toFixed(1)} 分</span><p>{compared.content}</p></article></div>
    </div>}
  </section>;
}
