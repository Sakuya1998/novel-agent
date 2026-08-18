import { CheckCircle2, Clock3, LoaderCircle, Save, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import {
  AGE_RATING_LABELS,
  createDefaultCreativeBrief,
  ENDING_TONE_LABELS,
  NARRATIVE_DISTANCE_LABELS,
  NARRATIVE_TENSE_LABELS,
  POINT_OF_VIEW_LABELS,
} from "../creativeBrief";
import type { CreativeBrief, CreativeBriefVersion } from "../types";

interface Props {
  open: boolean;
  brief?: CreativeBrief;
  version?: number;
  versions: CreativeBriefVersion[];
  disabled: boolean;
  onClose: () => void;
  onSubmit: (brief: CreativeBrief, changeSummary: string) => Promise<unknown>;
}

function splitList(value: string, limit: number): string[] {
  return value
    .split(/[，,；;\n]+/)
    .map((item) => item.trim().slice(0, 200))
    .filter((item, index, items) => item && items.indexOf(item) === index)
    .slice(0, limit);
}

export function CreativeBriefDialog({ open, brief, version, versions, disabled, onClose, onSubmit }: Props) {
  const [draft, setDraft] = useState<CreativeBrief>(createDefaultCreativeBrief);
  const [themes, setThemes] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [avoidContent, setAvoidContent] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const next = brief ?? createDefaultCreativeBrief();
    setDraft({
      ...createDefaultCreativeBrief(),
      ...next,
      intensity: { ...createDefaultCreativeBrief().intensity, ...next.intensity },
    });
    setThemes(next.themes.join("，"));
    setMustInclude(next.must_include.join("，"));
    setAvoidContent(next.avoid_content.join("，"));
    setChangeSummary("");
  }, [brief, open]);

  function update<K extends keyof CreativeBrief>(field: K, value: CreativeBrief[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function updateIntensity(field: keyof CreativeBrief["intensity"], value: number) {
    setDraft((current) => ({
      ...current,
      intensity: { ...current.intensity, [field]: value },
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSubmit({
        ...draft,
        target_audience: draft.target_audience.trim(),
        themes: splitList(themes, 8),
        must_include: splitList(mustInclude, 12),
        avoid_content: splitList(avoidContent, 12),
        notes: draft.notes.trim(),
      }, changeSummary.trim());
      onClose();
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;
  const busy = disabled || saving;
  return <div className="model-settings-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="model-settings-dialog creative-brief-dialog" role="dialog" aria-modal="true" aria-labelledby="creative-brief-title">
      <header className="model-settings-header">
        <div><span className="eyebrow">CREATIVE BRIEF</span><h2 id="creative-brief-title">创作约束</h2></div>
        <div className="model-settings-header-actions"><span className="model-source-badge database">版本 v{version ?? 1}</span><button className="dialog-close-button" type="button" title="关闭" aria-label="关闭创作约束" onClick={onClose}><X size={18} /></button></div>
      </header>
      <form onSubmit={submit}>
        <div className="creative-brief-dialog-content">
          <label>目标读者<input value={draft.target_audience} maxLength={200} onChange={(event) => update("target_audience", event.target.value)} required disabled={busy} /></label>
          <div className="brief-dialog-select-grid">
            <label>内容分级<select value={draft.age_rating} onChange={(event) => update("age_rating", event.target.value as CreativeBrief["age_rating"])} disabled={busy}>{Object.entries(AGE_RATING_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>叙事视角<select value={draft.point_of_view} onChange={(event) => update("point_of_view", event.target.value as CreativeBrief["point_of_view"])} disabled={busy}>{Object.entries(POINT_OF_VIEW_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>叙事时态<select value={draft.narrative_tense} onChange={(event) => update("narrative_tense", event.target.value as CreativeBrief["narrative_tense"])} disabled={busy}>{Object.entries(NARRATIVE_TENSE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>叙事距离<select value={draft.narrative_distance} onChange={(event) => update("narrative_distance", event.target.value as CreativeBrief["narrative_distance"])} disabled={busy}>{Object.entries(NARRATIVE_DISTANCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>结局基调<select value={draft.ending_tone} onChange={(event) => update("ending_tone", event.target.value as CreativeBrief["ending_tone"])} disabled={busy}>{Object.entries(ENDING_TONE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          </div>
          <fieldset className="brief-dialog-intensity"><legend><SlidersHorizontal size={14} />类型强度</legend>
            {([["romance", "感情"], ["mystery", "悬疑"], ["action", "动作"], ["darkness", "黑暗"]] as const).map(([field, label]) => <label className="brief-dialog-slider" key={field}><span>{label}<output>{draft.intensity[field]}</output></span><input type="range" min="0" max="5" aria-label={`${label}强度`} value={draft.intensity[field]} onChange={(event) => updateIntensity(field, Number(event.target.value))} disabled={busy} /></label>)}
          </fieldset>
          <label>核心主题<input value={themes} maxLength={1600} onChange={(event) => setThemes(event.target.value)} placeholder="身份，记忆，选择" disabled={busy} /></label>
          <label>必须包含<input value={mustInclude} maxLength={2400} onChange={(event) => setMustInclude(event.target.value)} placeholder="关键意象或情节承诺" disabled={busy} /></label>
          <label>回避内容<input value={avoidContent} maxLength={2400} onChange={(event) => setAvoidContent(event.target.value)} placeholder="不希望出现的内容" disabled={busy} /></label>
          <label>补充说明<textarea value={draft.notes} maxLength={2000} onChange={(event) => update("notes", event.target.value)} rows={4} disabled={busy} /></label>
          <label>本次修改说明<input value={changeSummary} maxLength={500} onChange={(event) => setChangeSummary(event.target.value)} placeholder="例如：降低黑暗度，改为开放式结局" disabled={busy} /></label>
          {versions.length > 0 && <section className="creative-brief-history"><div className="block-label"><Clock3 size={14} />版本历史</div>{versions.slice(0, 6).map((item) => <div className="creative-brief-history-row" key={item.id}><strong>v{item.version_number}</strong><span>{item.change_summary || "未填写说明"}</span><time>{item.created_at.slice(0, 16).replace("T", " ")}</time></div>)}</section>}
        </div>
        <footer className="creative-brief-dialog-footer"><span>{disabled ? <><CheckCircle2 size={14} />创作运行中，暂时只读</> : "保存后会重新校验受影响的章节"}</span><div><button type="button" className="secondary-button" onClick={onClose} disabled={saving}>取消</button><button type="submit" className="primary-button" disabled={busy}><Save size={14} />{saving ? <><LoaderCircle className="spin" size={14} />保存中</> : "保存约束"}</button></div></footer>
      </form>
    </section>
  </div>;
}
