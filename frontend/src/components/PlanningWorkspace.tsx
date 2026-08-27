import { Map, UsersRound } from "lucide-react";
import type { WorkbenchState } from "../types";

interface Props {
  state: WorkbenchState;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function PlanningWorkspace({ state }: Props) {
  const outline = state.outline ?? [];
  const characters = state.characters ?? [];
  const scenePlan = state.scene_plan ?? [];

  return (
    <section className="workspace-view planning-workspace" aria-labelledby="planning-view-title">
      <header className="workspace-view-header">
        <div><span className="section-label">STORY PLAN</span><h2 id="planning-view-title">故事规划</h2></div>
        <span>{outline.length} 章 · {characters.length} 位角色</span>
      </header>

      <section className="planning-summary-band">
        <div className="planning-summary-heading"><Map size={16} /><strong>世界观</strong></div>
        <p>{state.world_bible || "世界观将在创作运行后生成。"}</p>
      </section>

      <div className="planning-columns">
        <section>
          <div className="planning-summary-heading"><UsersRound size={16} /><strong>主要角色</strong></div>
          <div className="planning-character-list">
            {characters.map((character, index) => (
              <article key={`${text(character.name)}-${index}`}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{text(character.name) || "未命名角色"}</strong><small>{text(character.role) || text(character.personality) || "尚未设置角色定位"}</small></div>
              </article>
            ))}
            {characters.length === 0 ? <p className="workspace-view-empty">暂无角色设定</p> : null}
          </div>
        </section>

        <section>
          <div className="planning-summary-heading"><Map size={16} /><strong>{scenePlan.length ? "当前分镜" : "章节大纲"}</strong></div>
          <div className="planning-outline-list">
            {scenePlan.length ? scenePlan.map((scene) => (
              <article key={scene.scene_number}>
                <span>{String(scene.scene_number).padStart(2, "0")}</span>
                <div><strong>{scene.goal || "未命名场景"}</strong><small>{scene.location || "地点未定"} · {scene.emotion || "情绪未定"}</small></div>
                <em>{scene.estimated_words} 字</em>
              </article>
            )) : outline.map((chapter, index) => (
              <article key={`${text(chapter.chapter)}-${index}`}>
                <span>{String(Number(chapter.chapter) || index + 1).padStart(2, "0")}</span>
                <div><strong>{text(chapter.title) || `第 ${index + 1} 章`}</strong><small>{text(chapter.summary) || "暂无章节摘要"}</small></div>
              </article>
            ))}
            {!scenePlan.length && !outline.length ? <p className="workspace-view-empty">暂无章节规划</p> : null}
          </div>
        </section>
      </div>
    </section>
  );
}
