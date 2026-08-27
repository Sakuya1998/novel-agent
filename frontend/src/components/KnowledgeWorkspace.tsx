import { ArrowUpRight, BookKey, BrainCircuit, SlidersHorizontal } from "lucide-react";
import type { Novel, WorkbenchState } from "../types";

interface Props {
  novel: Novel;
  state: WorkbenchState;
  onOpenBrief: () => void;
  onOpenCanon: () => void;
  onOpenMemory: () => void;
}

export function KnowledgeWorkspace({ novel, state, onOpenBrief, onOpenCanon, onOpenMemory }: Props) {
  const brief = novel.creative_brief ?? state.creative_brief;
  const facts = (state.canon?.world_facts ?? 0) + (state.canon?.confirmed_facts ?? 0);

  return (
    <section className="workspace-view knowledge-workspace" aria-labelledby="knowledge-view-title">
      <header className="workspace-view-header">
        <div><span className="section-label">STORY KNOWLEDGE</span><h2 id="knowledge-view-title">设定与记忆</h2></div>
        <span>版本化保存</span>
      </header>

      <div className="knowledge-action-list">
        <button type="button" onClick={onOpenBrief}>
          <span className="knowledge-icon"><SlidersHorizontal size={18} /></span>
          <span><strong>创作约束</strong><small>{brief?.target_audience || "设置目标读者、视角和内容边界"}</small></span>
          <span className="knowledge-meta">v{novel.creative_brief_version ?? state.creative_brief_version ?? 1}</span>
          <ArrowUpRight size={16} />
        </button>
        <button type="button" onClick={onOpenCanon}>
          <span className="knowledge-icon"><BookKey size={18} /></span>
          <span><strong>事实与叙事线程</strong><small>{facts} 条事实 · {state.canon?.open_threads ?? 0} 条开放线索</small></span>
          <span className="knowledge-meta">Canon v{state.canon?.version ?? 0}</span>
          <ArrowUpRight size={16} />
        </button>
        <button type="button" onClick={onOpenMemory}>
          <span className="knowledge-icon"><BrainCircuit size={18} /></span>
          <span><strong>长期记忆</strong><small>{state.memory?.chapters ?? 0} 章记忆 · {state.memory?.arcs ?? 0} 个故事幕</small></span>
          <span className="knowledge-meta">质量检查</span>
          <ArrowUpRight size={16} />
        </button>
      </div>
    </section>
  );
}
