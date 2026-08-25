import { Check, LoaderCircle } from "lucide-react";
import { STAGES } from "../types";

interface Props { lastNode?: string; status: string; currentPhase: string; }

export function StageRail({ lastNode, status, currentPhase }: Props) {
  const groups = [
    { label: "故事基础", detail: "世界观、角色与大纲", stages: ["world_builder", "character_designer", "plot_planner", "blueprint_review"] },
    { label: "章节编排", detail: "章节计划与分镜", stages: ["scene_planner", "scene_review"] },
    { label: "正文写作", detail: "初稿、修订与润色", stages: ["scene_writer", "scene_rewriter", "style_editor"] },
    { label: "审校定稿", detail: "一致性、人工审查与终审", stages: ["consistency_checker", "human_review", "book_auditor"] },
  ];
  const statusNode = status.endsWith("_review") ? status : "";
  const activeIndex = Math.max(
    STAGES.findIndex((stage) => stage.id === statusNode),
    STAGES.findIndex((stage) => stage.id === lastNode),
    STAGES.findIndex((stage) => stage.id === currentPhase),
    0,
  );
  const activeNode = STAGES[activeIndex]?.label ?? "准备中";

  return (
    <section className="stage-section" aria-label="创作阶段">
      <div className="stage-section-heading"><span>创作流程</span><strong>当前：{activeNode}</strong></div>
      <div className="stage-rail">
        {groups.map((group, index) => {
          const indexes = group.stages.map((id) => STAGES.findIndex((stage) => stage.id === id));
          const complete = status === "completed" || indexes.every((stageIndex) => stageIndex < activeIndex);
          const active = !complete && indexes.includes(activeIndex);
          return (
            <div className={`stage ${complete ? "complete" : ""} ${active ? "active" : ""}`} key={group.label}>
              <div className="stage-icon">{complete ? <Check size={15} /> : active && status === "running" ? <LoaderCircle className="spin" size={15} /> : <span>{index + 1}</span>}</div>
              <div><strong>{group.label}</strong><small>{active ? activeNode : group.detail}</small></div>
              {index < groups.length - 1 && <i className={complete ? "filled" : ""} />}
            </div>
          );
        })}
      </div>
    </section>
  );
}
