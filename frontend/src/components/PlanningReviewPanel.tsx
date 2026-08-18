import { BookOpenCheck, CheckCircle2, Clapperboard, GitCompareArrows, History, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { PlanningReviewSubmission, PlanningVersion, ScenePlanItem } from "../types";

interface Props {
  reviewNode: "blueprint_review" | "scene_review";
  worldBible: string;
  characters: Record<string, unknown>[];
  outline: Record<string, unknown>[];
  scenePlan: ScenePlanItem[];
  planningVersions?: PlanningVersion[];
  disabled: boolean;
  onSubmit: (submission: PlanningReviewSubmission) => Promise<void>;
  onLoadVersion?: (versionNumber: number) => Promise<PlanningVersion>;
  onCompareVersions?: (fromVersion: number, toVersion: number) => Promise<string>;
}

const text = (value: unknown) => value == null ? "" : String(value);

export function PlanningReviewPanel({ reviewNode, worldBible, characters, outline, scenePlan, planningVersions = [], disabled, onSubmit, onLoadVersion, onCompareVersions }: Props) {
  const [world, setWorld] = useState(worldBible);
  const [characterRows, setCharacterRows] = useState(characters);
  const [outlineRows, setOutlineRows] = useState(outline);
  const [sceneRows, setSceneRows] = useState(scenePlan);
  const [submitting, setSubmitting] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [fromVersion, setFromVersion] = useState(0);
  const [toVersion, setToVersion] = useState(0);
  const [versionDiff, setVersionDiff] = useState("");

  useEffect(() => {
    setWorld(worldBible);
    setCharacterRows(characters);
    setOutlineRows(outline);
    setSceneRows(scenePlan);
  }, [worldBible, characters, outline, scenePlan, reviewNode]);

  useEffect(() => {
    const numbers = planningVersions.map((version) => version.version_number);
    const latest = numbers.at(-1) ?? 0;
    setFromVersion(numbers.at(-2) ?? latest);
    setToVersion(latest);
    setVersionDiff("");
  }, [planningVersions, reviewNode]);

  function updateCharacter(index: number, field: string, value: string) {
    setCharacterRows((rows) => rows.map((row, itemIndex) => itemIndex === index ? { ...row, [field]: value } : row));
  }

  function updateOutline(index: number, field: string, value: string | number) {
    setOutlineRows((rows) => rows.map((row, itemIndex) => itemIndex === index ? { ...row, [field]: value } : row));
  }

  function updateScene(index: number, field: keyof ScenePlanItem, value: string | number | string[]) {
    setSceneRows((rows) => rows.map((row, itemIndex) => itemIndex === index ? { ...row, [field]: value } : row));
  }

  function removeScene(index: number) {
    setSceneRows((rows) => {
      const removedBeats = rows[index]?.narrative_beats ?? [];
      const remaining = rows.filter((_, itemIndex) => itemIndex !== index).map((item, itemIndex) => ({
        ...item,
        scene_number: itemIndex + 1,
      }));
      if (remaining.length && removedBeats.length) {
        remaining[0] = {
          ...remaining[0],
          narrative_beats: [...(remaining[0].narrative_beats ?? []), ...removedBeats],
        };
      }
      return remaining;
    });
  }

  async function approve() {
    setSubmitting(true);
    try {
      if (reviewNode === "blueprint_review") {
        await onSubmit({ review_type: reviewNode, world_bible: world, characters: characterRows, outline: outlineRows });
      } else {
        await onSubmit({ review_type: reviewNode, scene_plan: sceneRows });
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function restoreVersion() {
    if (!toVersion || !onLoadVersion) return;
    setHistoryBusy(true);
    try {
      const version = await onLoadVersion(toVersion);
      const payload = version.payload ?? {};
      if (reviewNode === "blueprint_review") {
        setWorld(payload.world_bible ?? "");
        setCharacterRows(payload.characters ?? []);
        setOutlineRows(payload.outline ?? []);
      } else {
        setSceneRows(payload.scene_plan ?? []);
      }
      setVersionDiff("");
    } finally {
      setHistoryBusy(false);
    }
  }

  async function compareVersions() {
    if (!fromVersion || !toVersion || !onCompareVersions) return;
    setHistoryBusy(true);
    try {
      setVersionDiff(await onCompareVersions(fromVersion, toVersion));
    } finally {
      setHistoryBusy(false);
    }
  }

  return (
    <aside className="planning-review-panel">
      <header className="planning-review-header">
        {reviewNode === "blueprint_review" ? <BookOpenCheck size={18} /> : <Clapperboard size={18} />}
        <div><span>{reviewNode === "blueprint_review" ? "全书蓝图" : "本章分镜"}</span><h2>生成正文前审阅</h2></div>
      </header>

      <div className="planning-review-body">
        {reviewNode === "blueprint_review" ? <>
          <section className="planning-editor-section">
            <div className="section-heading"><strong>世界观圣经</strong></div>
            <textarea className="world-editor" aria-label="世界观圣经" value={world} onChange={(event) => setWorld(event.target.value)} rows={10} />
          </section>
          <section className="planning-editor-section">
            <div className="section-heading"><strong>角色</strong><button type="button" className="icon-button compact" title="添加角色" onClick={() => setCharacterRows((rows) => [...rows, { name: "", role: "" }])}><Plus size={14} /></button></div>
            <div className="structured-list">
              {characterRows.map((character, index) => <div className="character-editor" key={index}>
                <input aria-label={`角色 ${index + 1} 姓名`} value={text(character.name)} placeholder="姓名" onChange={(event) => updateCharacter(index, "name", event.target.value)} />
                <input aria-label={`角色 ${index + 1} 定位`} value={text(character.role)} placeholder="角色定位" onChange={(event) => updateCharacter(index, "role", event.target.value)} />
                <textarea aria-label={`角色 ${index + 1} 性格`} value={text(character.personality)} placeholder="性格与动机" rows={2} onChange={(event) => updateCharacter(index, "personality", event.target.value)} />
                <button type="button" className="icon-button compact danger" title="删除角色" onClick={() => setCharacterRows((rows) => rows.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={13} /></button>
              </div>)}
            </div>
          </section>
          <section className="planning-editor-section">
            <div className="section-heading"><strong>章节大纲</strong></div>
            <div className="structured-list">
              {outlineRows.map((chapter, index) => <div className="outline-editor" key={text(chapter.chapter) || index}>
                <span className="row-number">{text(chapter.chapter) || index + 1}</span>
                <input value={text(chapter.title)} placeholder="章节标题" onChange={(event) => updateOutline(index, "title", event.target.value)} />
                <textarea value={text(chapter.summary)} placeholder="本章摘要" rows={2} onChange={(event) => updateOutline(index, "summary", event.target.value)} />
                <input value={text(chapter.conflict)} placeholder="核心冲突" onChange={(event) => updateOutline(index, "conflict", event.target.value)} />
                <input value={text(chapter.cliffhanger)} placeholder="章末悬念" onChange={(event) => updateOutline(index, "cliffhanger", event.target.value)} />
                <input type="number" min="1" value={Number(chapter.estimated_words) || 1} aria-label={`第 ${index + 1} 章目标字数`} onChange={(event) => updateOutline(index, "estimated_words", Number(event.target.value))} />
              </div>)}
            </div>
          </section>
        </> : <section className="planning-editor-section">
          <div className="section-heading"><strong>场景序列</strong><button type="button" className="icon-button compact" title="添加场景" disabled={sceneRows.length >= 8} onClick={() => setSceneRows((rows) => [...rows, { scene_number: rows.length + 1, goal: "", conflict: "", turn: "", location: "", characters: [], emotion: "", estimated_words: 1 }])}><Plus size={14} /></button></div>
          <div className="structured-list">
            {sceneRows.map((scene, index) => <div className="scene-editor" key={scene.scene_number}>
              <span className="row-number">{index + 1}</span>
              <input value={scene.goal} placeholder="场景目标" onChange={(event) => updateScene(index, "goal", event.target.value)} />
              <input value={scene.conflict} placeholder="冲突" onChange={(event) => updateScene(index, "conflict", event.target.value)} />
              <input value={scene.turn} placeholder="转折" onChange={(event) => updateScene(index, "turn", event.target.value)} />
              <input value={scene.location} placeholder="地点" onChange={(event) => updateScene(index, "location", event.target.value)} />
              <input value={scene.characters.join("、")} placeholder="人物，以顿号分隔" onChange={(event) => updateScene(index, "characters", event.target.value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean))} />
              <input value={scene.emotion} placeholder="情绪" onChange={(event) => updateScene(index, "emotion", event.target.value)} />
              <input type="number" min="1" value={scene.estimated_words} aria-label={`场景 ${index + 1} 目标字数`} onChange={(event) => updateScene(index, "estimated_words", Number(event.target.value))} />
              <button type="button" className="icon-button compact danger" title="删除场景" disabled={sceneRows.length <= 1} onClick={() => removeScene(index)}><Trash2 size={13} /></button>
            </div>)}
          </div>
        </section>}
        {planningVersions.length > 0 && <section className="planning-editor-section planning-version-section">
          <div className="section-heading"><strong><History size={14} />版本历史</strong></div>
          <div className="planning-version-list">
            {planningVersions.map((version) => <div className="planning-version-row" key={version.id}>
              <span>v{version.version_number}</span>
              <div><strong>{version.source === "generated" ? "生成稿" : version.source === "approved" ? "批准稿" : version.source}</strong><small>{version.preview}</small></div>
              <time>{new Date(version.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</time>
            </div>)}
          </div>
          <div className="planning-version-controls">
            <select aria-label="起始规划版本" value={fromVersion} onChange={(event) => { setFromVersion(Number(event.target.value)); setVersionDiff(""); }}>{planningVersions.map((version) => <option value={version.version_number} key={version.id}>v{version.version_number}</option>)}</select>
            <span>至</span>
            <select aria-label="目标规划版本" value={toVersion} onChange={(event) => { setToVersion(Number(event.target.value)); setVersionDiff(""); }}>{planningVersions.map((version) => <option value={version.version_number} key={version.id}>v{version.version_number}</option>)}</select>
            <button type="button" className="secondary-button" disabled={disabled || historyBusy || fromVersion === toVersion} onClick={() => void compareVersions()}><GitCompareArrows size={14} />比较</button>
            <button type="button" className="secondary-button" disabled={disabled || historyBusy || !toVersion} onClick={() => void restoreVersion()}><RotateCcw size={14} />回滚到此版本</button>
          </div>
          {versionDiff && <pre className="planning-version-diff">{versionDiff}</pre>}
        </section>}
      </div>
      <footer className="planning-review-footer"><button className="primary-button full-width" disabled={disabled || submitting} onClick={() => void approve()}><CheckCircle2 size={15} />{submitting ? "提交中" : "批准并继续"}</button></footer>
    </aside>
  );
}
