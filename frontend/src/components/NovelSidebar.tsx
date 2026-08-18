import { BookOpen, LoaderCircle, Plus, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";
import type { CreateNovelPayload } from "../api";
import {
  AGE_RATING_LABELS,
  createDefaultCreativeBrief,
  ENDING_TONE_LABELS,
  NARRATIVE_DISTANCE_LABELS,
  NARRATIVE_TENSE_LABELS,
  POINT_OF_VIEW_LABELS,
} from "../creativeBrief";
import type { CreativeBrief, Novel } from "../types";

interface Props {
  novels: Novel[];
  selectedId?: string;
  isLoading: boolean;
  isStreaming: boolean;
  deletingId?: string;
  onSelect: (id: string) => void;
  onCreate: (payload: CreateNovelPayload) => Promise<void>;
  onDelete: (novel: Novel) => Promise<void>;
}

function splitBriefList(value: string, limit: number): string[] {
  return value
    .split(/[，,；;\n]+/)
    .map((item) => item.trim().slice(0, 200))
    .filter((item, index, items) => item && items.indexOf(item) === index)
    .slice(0, limit);
}

export function NovelSidebar({ novels, selectedId, isLoading, isStreaming, deletingId, onSelect, onCreate, onDelete }: Props) {
  const [isCreating, setIsCreating] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [title, setTitle] = useState("");
  const [genre, setGenre] = useState("武侠");
  const [inspiration, setInspiration] = useState("");
  const [totalChapters, setTotalChapters] = useState(3);
  const [style, setStyle] = useState("jin_yong");
  const [planningReviewEnabled, setPlanningReviewEnabled] = useState(true);
  const [creativeBrief, setCreativeBrief] = useState(createDefaultCreativeBrief);
  const [themes, setThemes] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [avoidContent, setAvoidContent] = useState("");

  function updateBrief<K extends keyof CreativeBrief>(field: K, value: CreativeBrief[K]) {
    setCreativeBrief((current) => ({ ...current, [field]: value }));
  }

  function updateIntensity(field: keyof CreativeBrief["intensity"], value: number) {
    setCreativeBrief((current) => ({
      ...current,
      intensity: { ...current.intensity, [field]: value },
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !inspiration.trim()) return;
    setIsSubmitting(true);
    try {
      await onCreate({
        title: title.trim(),
        genre,
        inspiration: inspiration.trim(),
        total_chapters: totalChapters,
        style,
        planning_review_enabled: planningReviewEnabled,
        creative_brief: {
          ...creativeBrief,
          target_audience: creativeBrief.target_audience.trim(),
          themes: splitBriefList(themes, 8),
          must_include: splitBriefList(mustInclude, 12),
          avoid_content: splitBriefList(avoidContent, 12),
          notes: creativeBrief.notes.trim(),
        },
      });
      setTitle("");
      setInspiration("");
      setCreativeBrief(createDefaultCreativeBrief());
      setThemes("");
      setMustInclude("");
      setAvoidContent("");
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
          <details className="creative-brief-fields">
            <summary><SlidersHorizontal size={14} />创作约束</summary>
            <div className="creative-brief-body">
              <label>目标读者<input value={creativeBrief.target_audience} maxLength={200} onChange={(event) => updateBrief("target_audience", event.target.value)} required /></label>
              <div className="brief-select-grid">
                <label>内容分级<select value={creativeBrief.age_rating} onChange={(event) => updateBrief("age_rating", event.target.value as CreativeBrief["age_rating"])}>{Object.entries(AGE_RATING_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>叙事视角<select value={creativeBrief.point_of_view} onChange={(event) => updateBrief("point_of_view", event.target.value as CreativeBrief["point_of_view"])}>{Object.entries(POINT_OF_VIEW_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>叙事时态<select value={creativeBrief.narrative_tense} onChange={(event) => updateBrief("narrative_tense", event.target.value as CreativeBrief["narrative_tense"])}>{Object.entries(NARRATIVE_TENSE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>叙事距离<select value={creativeBrief.narrative_distance} onChange={(event) => updateBrief("narrative_distance", event.target.value as CreativeBrief["narrative_distance"])}>{Object.entries(NARRATIVE_DISTANCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>结局基调<select value={creativeBrief.ending_tone} onChange={(event) => updateBrief("ending_tone", event.target.value as CreativeBrief["ending_tone"])}>{Object.entries(ENDING_TONE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              </div>
              <fieldset className="brief-intensity">
                <legend>类型强度</legend>
                {([["romance", "感情"], ["mystery", "悬疑"], ["action", "动作"], ["darkness", "黑暗"]] as const).map(([field, label]) => (
                  <label className="brief-slider" key={field}>
                    <span>{label}<output>{creativeBrief.intensity[field]}</output></span>
                    <input aria-label={`${label}强度`} type="range" min="0" max="5" value={creativeBrief.intensity[field]} onChange={(event) => updateIntensity(field, Number(event.target.value))} />
                  </label>
                ))}
              </fieldset>
              <label>核心主题<input value={themes} maxLength={1600} onChange={(event) => setThemes(event.target.value)} placeholder="身份，记忆，选择" /></label>
              <label>必须包含<input value={mustInclude} maxLength={2400} onChange={(event) => setMustInclude(event.target.value)} placeholder="关键意象或情节承诺" /></label>
              <label>回避内容<input value={avoidContent} maxLength={2400} onChange={(event) => setAvoidContent(event.target.value)} placeholder="不希望出现的内容" /></label>
              <label>补充说明<textarea value={creativeBrief.notes} maxLength={2000} onChange={(event) => updateBrief("notes", event.target.value)} rows={3} /></label>
            </div>
          </details>
          <label className="toggle-row"><input type="checkbox" checked={planningReviewEnabled} onChange={(event) => setPlanningReviewEnabled(event.target.checked)} /><span>正文生成前审阅蓝图与分镜</span></label>
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
