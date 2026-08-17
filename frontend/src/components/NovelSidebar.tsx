import { BookOpen, LoaderCircle, Plus, Sparkles, Trash2 } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";
import type { Novel } from "../types";

interface Props {
  novels: Novel[];
  selectedId?: string;
  isLoading: boolean;
  isStreaming: boolean;
  deletingId?: string;
  onSelect: (id: string) => void;
  onCreate: (payload: Pick<Novel, "title" | "genre" | "inspiration" | "total_chapters" | "style">) => Promise<void>;
  onDelete: (novel: Novel) => Promise<void>;
}

export function NovelSidebar({ novels, selectedId, isLoading, isStreaming, deletingId, onSelect, onCreate, onDelete }: Props) {
  const [isCreating, setIsCreating] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [title, setTitle] = useState("");
  const [genre, setGenre] = useState("武侠");
  const [inspiration, setInspiration] = useState("");
  const [totalChapters, setTotalChapters] = useState(3);
  const [style, setStyle] = useState("jin_yong");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !inspiration.trim()) return;
    setIsSubmitting(true);
    try {
      await onCreate({ title: title.trim(), genre, inspiration: inspiration.trim(), total_chapters: totalChapters, style });
      setTitle("");
      setInspiration("");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDelete(novel: Novel) {
    const confirmed = window.confirm(`确认删除《${novel.title}》吗？\n这将删除章节、进度和检查点，且无法恢复。`);
    if (!confirmed) return;
    await onDelete(novel);
  }

  return (
    <aside className="sidebar">
      <div className="brand-lockup">
        <div className="brand-mark"><BookOpen size={18} /></div>
        <div><strong>墨笔</strong><span>AI 小说工作台</span></div>
      </div>
      <div className="sidebar-heading">
        <div><span className="eyebrow">LIBRARY</span><h2>我的作品</h2></div>
        <button className="icon-button" title="新建作品" onClick={() => setIsCreating((value) => !value)}><Plus size={17} /></button>
      </div>
      {isCreating && (
        <form className="new-novel-form" onSubmit={submit}>
          <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="雾中剑" required /></label>
          <label>类型<select value={genre} onChange={(event) => setGenre(event.target.value)}><option>武侠</option><option>仙侠</option><option>科幻</option><option>悬疑</option><option>都市</option><option>历史</option></select></label>
          <label>章节数<input type="number" min="1" max="50" value={totalChapters} onChange={(event) => setTotalChapters(Number(event.target.value))} /></label>
          <label>叙事风格<select value={style} onChange={(event) => setStyle(event.target.value)}><option value="jin_yong">金庸</option><option value="gu_long">古龙</option><option value="murakami">村上春树</option><option value="yu_hua">余华</option></select></label>
          <label>一句话灵感<textarea value={inspiration} onChange={(event) => setInspiration(event.target.value)} placeholder="一个失忆的剑客在雾都寻找过去……" rows={3} required /></label>
          <button className="primary-button full-width" disabled={isSubmitting || isStreaming}><Sparkles size={15} />{isSubmitting ? "启动中" : "开始创作"}</button>
        </form>
      )}
      <div className="novel-list" aria-label="作品列表">
        {isLoading && <div className="muted-row"><LoaderCircle className="spin" size={15} />加载作品</div>}
        {!isLoading && novels.length === 0 && <div className="empty-sidebar">还没有作品<br /><span>从右上角开始第一部小说</span></div>}
        {novels.map((item) => (
          <div
            className={`novel-item ${item.id === selectedId ? "active" : ""}`}
            key={item.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(item.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") onSelect(item.id);
            }}
          >
            <span className="novel-dot" /><span className="novel-item-copy"><strong>{item.title}</strong><small>{item.genre || "未分类"} · {item.total_chapters} 章</small></span>
            <button
              type="button"
              className="novel-delete-button"
              title="删除作品"
              aria-label={`删除《${item.title}》`}
              disabled={isStreaming || deletingId === item.id}
              onClick={(event) => {
                event.stopPropagation();
                void handleDelete(item).catch(() => undefined);
              }}
            >
              {deletingId === item.id ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
            </button>
          </div>
        ))}
      </div>
      <div className="sidebar-footer"><span className="status-dot online" />后端服务已连接<span className="version">v2.0</span></div>
    </aside>
  );
}
