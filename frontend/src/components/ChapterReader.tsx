import { useEffect, useRef } from "react";
import { AlignLeft, BookOpenText, Clock3 } from "lucide-react";
import type { Chapter, Draft } from "../types";

interface Props {
  draft: Draft;
  chapters: Chapter[];
  status: string;
  selectedSceneNumber?: number;
  focusRequest?: number;
  focusTarget?: "scene" | "top";
}

export function ChapterReader({
  draft,
  chapters,
  status,
  selectedSceneNumber,
  focusRequest = 0,
  focusTarget = "scene",
}: Props) {
  const manuscriptRef = useRef<HTMLElement>(null);
  const sceneRefs = useRef(new Map<number, HTMLElement>());
  const hasSceneDrafts = Boolean(draft.scene_drafts?.length);
  const hasDraft = hasSceneDrafts || Boolean(draft.content);

  useEffect(() => {
    if (focusRequest <= 0) return;
    const target = focusTarget === "top" ? manuscriptRef.current
      : selectedSceneNumber === undefined ? undefined : sceneRefs.current.get(selectedSceneNumber);
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusRequest, focusTarget, selectedSceneNumber]);

  return <section className="reader-panel">
    <div className="section-kicker"><BookOpenText size={15} />稿件阅读</div>
    {hasDraft ? <article className="manuscript" ref={manuscriptRef} tabIndex={-1}>
      <div className="manuscript-meta"><span>第 {draft.chapter_number ?? "—"} 章</span><span className="meta-divider">/</span><span>{status === "human_review" ? "待审查稿" : "当前稿件"}</span></div>
      <h2>{draft.title || "未命名章节"}</h2>
      <div className="manuscript-stats"><span><AlignLeft size={14} />{draft.word_count || (draft.content?.length ?? 0)} 字</span><span><Clock3 size={14} />实时生成</span></div>
      <div className="manuscript-content">
        {hasSceneDrafts ? draft.scene_drafts?.map((scene) => <section
          key={scene.scene_number}
          ref={(element) => {
            if (element) sceneRefs.current.set(scene.scene_number, element);
            else sceneRefs.current.delete(scene.scene_number);
          }}
          className="manuscript-scene"
          tabIndex={-1}
          data-scene-number={scene.scene_number}
          data-testid={`scene-${scene.scene_number}`}
          aria-current={selectedSceneNumber === scene.scene_number ? "true" : undefined}
        >{scene.content}</section>) : draft.content}
      </div>
    </article> : chapters.length ? <div className="chapter-list">{chapters.map((chapter) => <article className="chapter-row" key={chapter.chapter_number}><span className="chapter-number">{String(chapter.chapter_number).padStart(2, "0")}</span><div><strong>{chapter.title || `第${chapter.chapter_number}章`}</strong><p>{chapter.summary || "暂无摘要"}</p></div><span className="chapter-words">{chapter.word_count || 0} 字</span></article>)}</div> : <div className="reader-empty"><BookOpenText size={26} /><strong>稿件将在这里展开</strong><span>启动创作后，世界观、章节和审查结果会按阶段出现。</span></div>}
  </section>;
}
