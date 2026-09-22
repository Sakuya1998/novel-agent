import { Gauge } from "lucide-react";
import { AGE_RATING_LABELS, POINT_OF_VIEW_LABELS } from "../creativeBrief";
import type { Novel, WorkbenchState } from "../types";

interface Props {
  novel: Novel;
  state: WorkbenchState;
  statusLabel: string;
}

function formatTokens(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: value > 9999 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function styleLabel(style: string) {
  const labels: Record<string, string> = {
    jin_yong: "金庸式",
    gu_long: "古龙式",
    murakami: "村上式",
    yu_hua: "余华式",
  };
  return labels[style] || style || "默认";
}

export function ProjectOverview({ novel, state, statusLabel }: Props) {
  const brief = novel.creative_brief ?? state.creative_brief;
  const progress = state.total_chapters ? Math.min(100, Math.round((state.chapters_done / state.total_chapters) * 100)) : 0;

  return (
    <section className="project-overview">
      <div className="project-heading">
        <div className="project-title-row">
          <span className={`project-status status-${state.status}`}><i />{statusLabel}</span>
          <span>{novel.genre || "未分类"}</span>
        </div>
        <h1>{novel.title}</h1>
        <p>{novel.inspiration}</p>
      </div>

      <div className="progress-summary">
        <div className="progress-heading">
          <span>全书进度</span>
          <strong>{progress}%</strong>
        </div>
        <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
        <div className="progress-detail"><strong>{state.chapters_done}</strong><span>已完成</span><i /><strong>{state.total_chapters}</strong><span>总章节</span></div>
      </div>

      <div className="project-metrics">
        <div><span>叙事风格</span><strong>{styleLabel(novel.style)}</strong></div>
        <div><span>创作口径</span><strong>{brief ? POINT_OF_VIEW_LABELS[brief.point_of_view] : "未设置"}</strong><small>{brief ? AGE_RATING_LABELS[brief.age_rating] : ""}</small></div>
        <div><span>设定事实</span><strong>{(state.canon?.world_facts ?? 0) + (state.canon?.confirmed_facts ?? 0)}</strong><small>{state.canon?.open_threads ?? 0} 条开放线索</small></div>
        <div><span>上下文记忆</span><strong>{state.memory?.chapters ?? 0} 章</strong><small>{state.memory?.arcs ?? 0} 个故事幕</small></div>
        <div><span><Gauge size={13} />模型用量</span><strong>{formatTokens(state.model_usage?.total_tokens ?? 0)}</strong><small>tokens</small></div>
      </div>
    </section>
  );
}
