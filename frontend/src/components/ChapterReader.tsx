import { AlignLeft, BookOpenText, Clock3 } from "lucide-react";
import type { Chapter, Draft } from "../types";

interface Props { draft: Draft; chapters: Chapter[]; status: string; }

export function ChapterReader({ draft, chapters, status }: Props) {
  const hasDraft = Boolean(draft.content);
  return <section className="reader-panel">
    <div className="section-kicker"><BookOpenText size={15} />稿件阅读</div>
    {hasDraft ? <article className="manuscript">
      <div className="manuscript-meta"><span>第 {draft.chapter_number ?? "—"} 章</span><span className="meta-divider">/</span><span>{status === "human_review" ? "待审查稿" : "当前稿件"}</span></div>
      <h2>{draft.title || "未命名章节"}</h2>
      <div className="manuscript-stats"><span><AlignLeft size={14} />{draft.word_count || (draft.content?.length ?? 0)} 字</span><span><Clock3 size={14} />实时生成</span></div>
      <div className="manuscript-content">{draft.content}</div>
    </article> : chapters.length ? <div className="chapter-list">{chapters.map((chapter) => <article className="chapter-row" key={chapter.chapter_number}><span className="chapter-number">{String(chapter.chapter_number).padStart(2, "0")}</span><div><strong>{chapter.title || `第${chapter.chapter_number}章`}</strong><p>{chapter.summary || "暂无摘要"}</p></div><span className="chapter-words">{chapter.word_count || 0} 字</span></article>)}</div> : <div className="reader-empty"><BookOpenText size={26} /><strong>稿件将在这里展开</strong><span>启动创作后，世界观、章节和审查结果会按阶段出现。</span></div>}
  </section>;
}
