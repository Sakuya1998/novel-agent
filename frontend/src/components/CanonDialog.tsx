import { AlertCircle, Edit3, History, Link2, LoaderCircle, Plus, RotateCcw, Save, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getNovelCanon } from "../api";
import type { CanonCharacter, CanonDetail, CanonFact, CanonOperation, CanonWorldFact, ScenePlanItem } from "../types";
import { NarrativeThreadsPanel } from "./NarrativeThreadsPanel";

type Tab = "world" | "facts" | "threads" | "characters" | "audit";
type FactEditor = { targetType: "world_fact" | "fact"; targetId?: string; path: string; subject: string; kind: string; value: string };
type StatusEditor = { action: "deprecate_fact" | "confirm_fact"; targetType: "world_fact" | "fact"; targetId: string; label: string };

interface Props {
  open: boolean;
  novelId?: string;
  editable: boolean;
  disabled: boolean;
  onClose: () => void;
  onSubmit: (operation: CanonOperation) => Promise<void>;
  currentChapter?: number;
  scenePlan?: ScenePlanItem[];
}

const emptyFactEditor = (targetType: "world_fact" | "fact"): FactEditor => ({ targetType, path: "", subject: "", kind: "manual", value: "" });

export function CanonDialog({ open, novelId, editable, disabled, onClose, onSubmit, currentChapter, scenePlan }: Props) {
  const [tab, setTab] = useState<Tab>("world");
  const [canon, setCanon] = useState<CanonDetail>();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [factEditor, setFactEditor] = useState<FactEditor>();
  const [statusEditor, setStatusEditor] = useState<StatusEditor>();
  const [characterName, setCharacterName] = useState<string>();
  const [characterPatch, setCharacterPatch] = useState<Record<string, string>>({});
  const [alias, setAlias] = useState("");
  const [canonicalName, setCanonicalName] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    if (!open || !novelId) return;
    setIsLoading(true);
    setError("");
    try { setCanon(await getNovelCanon(novelId)); }
    catch (err) { setError(err instanceof Error ? err.message : "无法加载 Canon"); }
    finally { setIsLoading(false); }
  }, [novelId, open]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  const characters = useMemo(() => Object.values(canon?.characters ?? {}), [canon]);
  const canMutate = editable && !disabled && !submitting;

  function resetEditor() {
    setFactEditor(undefined);
    setStatusEditor(undefined);
    setCharacterName(undefined);
    setCharacterPatch({});
    setReason("");
  }

  async function submit(operation: CanonOperation): Promise<boolean> {
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(operation);
      resetEditor();
      await load();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Canon 更新失败");
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  function editFact(item: CanonWorldFact | CanonFact, targetType: "world_fact" | "fact") {
    const fact = item as CanonFact;
    const world = item as CanonWorldFact;
    setFactEditor({ targetType, targetId: item.id, path: world.path ?? "", subject: fact.subject ?? "", kind: fact.kind ?? "manual", value: item.value });
    setStatusEditor(undefined);
    setCharacterName(undefined);
    setReason("");
  }

  function editCharacter(character: CanonCharacter) {
    setCharacterName(character.name);
    setCharacterPatch({
      role: character.role ?? "",
      personality: character.personality ?? "",
      relationships: character.relationships?.length
        ? JSON.stringify(character.relationships, null, 2)
        : "",
      speech_pattern: character.speech_pattern ?? "",
      behavior: character.behavior ?? "",
      arc: character.arc ?? "",
    });
    setFactEditor(undefined);
    setStatusEditor(undefined);
    setReason("");
  }

  if (!open) return null;

  return <div className="model-settings-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="canon-dialog" role="dialog" aria-modal="true" aria-labelledby="canon-title">
      <header className="model-settings-header">
        <div><span className="eyebrow">CANON CONTROL</span><h2 id="canon-title">设定治理</h2></div>
        <div className="model-settings-header-actions"><span className={`model-source-badge ${editable ? "database" : "environment"}`}>{editable ? "可编辑" : "只读"}</span><button className="dialog-close-button" type="button" title="关闭" aria-label="关闭 Canon" onClick={onClose}><X size={18} /></button></div>
      </header>
      <div className="model-settings-tabs" role="tablist" aria-label="Canon 视图">
        <button role="tab" aria-selected={tab === "world"} className={tab === "world" ? "active" : ""} onClick={() => { setTab("world"); resetEditor(); }}>世界事实</button>
        <button role="tab" aria-selected={tab === "facts"} className={tab === "facts" ? "active" : ""} onClick={() => { setTab("facts"); resetEditor(); }}>章节事实</button>
        <button role="tab" aria-selected={tab === "threads"} className={tab === "threads" ? "active" : ""} onClick={() => { setTab("threads"); resetEditor(); }}>叙事线程</button>
        <button role="tab" aria-selected={tab === "characters"} className={tab === "characters" ? "active" : ""} onClick={() => { setTab("characters"); resetEditor(); }}>角色与别名</button>
        <button role="tab" aria-selected={tab === "audit"} className={tab === "audit" ? "active" : ""} onClick={() => { setTab("audit"); resetEditor(); }}>审计记录</button>
      </div>
      {!editable && <div className="model-settings-running"><AlertCircle size={15} />Canon 仅在章节人工审查阶段开放修改。</div>}
      {error && <div className="model-settings-message error"><AlertCircle size={15} />{error}</div>}
      <div className="canon-content">
        {isLoading && !canon ? <div className="model-settings-loading"><LoaderCircle className="spin" size={18} />加载 Canon</div> : null}
        {canon && tab === "threads" ? <NarrativeThreadsPanel threads={canon.narrative_threads} canMutate={canMutate} onSubmit={submit} currentChapter={currentChapter} scenePlan={scenePlan} /> : null}
        {canon && tab !== "threads" && <div className={`canon-layout ${factEditor || statusEditor || characterName ? "with-editor" : ""}`}>
          <div className="canon-list-pane">
            {tab === "world" && <FactList title="世界事实" items={canon.world_facts} targetType="world_fact" canMutate={canMutate} onAdd={() => { resetEditor(); setFactEditor(emptyFactEditor("world_fact")); }} onEdit={editFact} onStatus={(item, action) => { resetEditor(); setStatusEditor({ action, targetType: "world_fact", targetId: item.id, label: (item as CanonWorldFact).path }); }} />}
            {tab === "facts" && <FactList title="章节事实" items={canon.facts} targetType="fact" canMutate={canMutate} onAdd={() => { resetEditor(); setFactEditor(emptyFactEditor("fact")); }} onEdit={editFact} onStatus={(item, action) => { resetEditor(); setStatusEditor({ action, targetType: "fact", targetId: item.id, label: (item as CanonFact).subject }); }} />}
            {tab === "characters" && <div className="canon-section">
              <div className="canon-toolbar"><div><strong>角色档案</strong><span>{characters.length} 位规范角色 · {Object.keys(canon.aliases).length} 个别名</span></div></div>
              <div className="canon-table"><div className="canon-table-head character"><span>角色</span><span>身份 / 最近出场</span><span>操作</span></div>{characters.map((character) => <div className="canon-table-row character" key={character.name}><div><strong>{character.name}</strong><small>{character.personality || "未记录性格"}</small></div><div><span>{character.role || "未设定"}</span><small>第 {character.last_seen_chapter || 0} 章</small></div><div className="canon-row-actions"><button title="编辑角色" aria-label={`编辑角色 ${character.name}`} disabled={!canMutate} onClick={() => editCharacter(character)}><Edit3 size={14} /></button></div></div>)}</div>
              <form className="canon-alias-form" onSubmit={(event) => { event.preventDefault(); void submit({ action: "merge_alias", alias: alias.trim(), canonical_name: canonicalName, reason: reason.trim() }); }}><div className="canon-form-heading"><Link2 size={15} /><strong>合并角色别名</strong></div><label>别名<input aria-label="角色别名" value={alias} onChange={(event) => setAlias(event.target.value)} disabled={!canMutate || Boolean(characterName)} /></label><label>规范角色<select aria-label="规范角色" value={canonicalName} onChange={(event) => setCanonicalName(event.target.value)} disabled={!canMutate || Boolean(characterName)}><option value="">选择角色</option>{characters.map((item) => <option value={item.name} key={item.name}>{item.name}</option>)}</select></label><label className="canon-reason-field">变更原因<input aria-label="别名合并原因" value={!characterName ? reason : ""} onChange={(event) => setReason(event.target.value)} disabled={!canMutate || Boolean(characterName)} /></label><button className="secondary-button" disabled={!canMutate || Boolean(characterName) || !alias.trim() || !canonicalName || !reason.trim()}><Link2 size={14} />合并别名</button></form>
              {Object.keys(canon.aliases).length > 0 && <div className="canon-alias-list">{Object.entries(canon.aliases).map(([from, to]) => <span key={from}>{from} <strong>→</strong> {to}</span>)}</div>}
            </div>}
            {tab === "audit" && <div className="canon-section"><div className="canon-toolbar"><div><strong>人工变更记录</strong><span>最近 {canon.audit.length} 条</span></div></div><div className="canon-audit-list">{[...canon.audit].reverse().map((entry) => <div className="canon-audit-row" key={entry.id}><History size={14} /><div><strong>{actionLabel(entry.action)}</strong><span>{entry.target}</span><p>{entry.reason}</p></div><time>{formatTime(entry.created_at)}</time></div>)}{canon.audit.length === 0 && <div className="canon-empty">尚无人工变更记录</div>}</div></div>}
          </div>
          {factEditor && <form className="canon-editor-pane" onSubmit={(event) => { event.preventDefault(); void submit({ action: "upsert_fact", target_type: factEditor.targetType, target_id: factEditor.targetId, path: factEditor.targetType === "world_fact" ? factEditor.path.trim() : undefined, subject: factEditor.targetType === "fact" ? factEditor.subject.trim() : undefined, kind: factEditor.targetType === "fact" ? factEditor.kind.trim() : undefined, value: factEditor.value.trim(), reason: reason.trim() }); }}><EditorHeading title={factEditor.targetId ? "编辑事实" : "新增事实"} onClose={resetEditor} />{factEditor.targetType === "world_fact" ? <label>路径<input aria-label="事实路径" value={factEditor.path} onChange={(event) => setFactEditor({ ...factEditor, path: event.target.value })} /></label> : <><label>主体<input aria-label="事实主体" value={factEditor.subject} onChange={(event) => setFactEditor({ ...factEditor, subject: event.target.value })} /></label><label>类型<input aria-label="事实类型" value={factEditor.kind} onChange={(event) => setFactEditor({ ...factEditor, kind: event.target.value })} /></label></>}<label>事实内容<textarea aria-label="事实内容" rows={6} value={factEditor.value} onChange={(event) => setFactEditor({ ...factEditor, value: event.target.value })} /></label><ReasonField value={reason} onChange={setReason} /><button className="primary-button" disabled={!canMutate || !reason.trim() || !factEditor.value.trim() || (factEditor.targetType === "world_fact" ? !factEditor.path.trim() : !factEditor.subject.trim())}><Save size={14} />保存事实</button></form>}
          {statusEditor && <form className="canon-editor-pane" onSubmit={(event) => { event.preventDefault(); void submit({ action: statusEditor.action, target_type: statusEditor.targetType, target_id: statusEditor.targetId, reason: reason.trim() }); }}><EditorHeading title={statusEditor.action === "deprecate_fact" ? "废止事实" : "重新确认事实"} onClose={resetEditor} /><div className="canon-target-summary">{statusEditor.label}</div><ReasonField value={reason} onChange={setReason} /><button className={statusEditor.action === "deprecate_fact" ? "secondary-button" : "primary-button"} disabled={!canMutate || !reason.trim()}>{statusEditor.action === "deprecate_fact" ? <Trash2 size={14} /> : <RotateCcw size={14} />}{statusEditor.action === "deprecate_fact" ? "确认废止" : "恢复为有效"}</button></form>}
          {characterName && <form className="canon-editor-pane" onSubmit={(event) => { event.preventDefault(); void submit({ action: "update_character", name: characterName, patch: characterOperationPatch(characterPatch), reason: reason.trim() }); }}><EditorHeading title={`编辑 ${characterName}`} onClose={resetEditor} /><label>身份<input aria-label="角色身份" value={characterPatch.role} onChange={(event) => setCharacterPatch({ ...characterPatch, role: event.target.value })} /></label><label>性格<textarea aria-label="角色性格" rows={3} value={characterPatch.personality} onChange={(event) => setCharacterPatch({ ...characterPatch, personality: event.target.value })} /></label><label>角色关系 JSON<textarea aria-label="角色关系" rows={5} value={characterPatch.relationships} onChange={(event) => setCharacterPatch({ ...characterPatch, relationships: event.target.value })} placeholder='[{"target":"某角色","relation":"盟友"}]' /></label><label>语言习惯<textarea aria-label="语言习惯" rows={3} value={characterPatch.speech_pattern} onChange={(event) => setCharacterPatch({ ...characterPatch, speech_pattern: event.target.value })} /></label><label>行为准则<textarea aria-label="行为准则" rows={3} value={characterPatch.behavior} onChange={(event) => setCharacterPatch({ ...characterPatch, behavior: event.target.value })} /></label><label>角色弧光<textarea aria-label="角色弧光" rows={3} value={characterPatch.arc} onChange={(event) => setCharacterPatch({ ...characterPatch, arc: event.target.value })} /></label><ReasonField value={reason} onChange={setReason} /><button className="primary-button" disabled={!canMutate || !reason.trim()}><Save size={14} />保存角色</button></form>}
        </div>}
      </div>
    </section>
  </div>;
}

function FactList({ title, items, targetType, canMutate, onAdd, onEdit, onStatus }: { title: string; items: (CanonWorldFact | CanonFact)[]; targetType: "world_fact" | "fact"; canMutate: boolean; onAdd: () => void; onEdit: (item: CanonWorldFact | CanonFact, targetType: "world_fact" | "fact") => void; onStatus: (item: CanonWorldFact | CanonFact, action: "deprecate_fact" | "confirm_fact") => void }) {
  return <div className="canon-section"><div className="canon-toolbar"><div><strong>{title}</strong><span>{items.filter((item) => item.status !== "deprecated").length} 条有效 · {items.filter((item) => item.status === "deprecated").length} 条已废止</span></div><button className="secondary-button" onClick={onAdd} disabled={!canMutate}><Plus size={14} />新增</button></div><div className="canon-table"><div className="canon-table-head"><span>{targetType === "world_fact" ? "路径" : "主体 / 类型"}</span><span>事实内容</span><span>操作</span></div>{items.map((item) => { const label = targetType === "world_fact" ? (item as CanonWorldFact).path : (item as CanonFact).subject; const meta = targetType === "world_fact" ? item.source : (item as CanonFact).kind; const deprecated = item.status === "deprecated"; return <div className={`canon-table-row ${deprecated ? "deprecated" : ""}`} key={item.id}><div><strong>{label}</strong><small>{meta || "manual"}</small></div><p>{item.value}</p><div className="canon-row-actions"><button title="编辑" aria-label={`编辑 ${label}`} disabled={!canMutate} onClick={() => onEdit(item, targetType)}><Edit3 size={14} /></button><button title={deprecated ? "重新确认" : "废止"} aria-label={`${deprecated ? "重新确认" : "废止"} ${label}`} disabled={!canMutate} onClick={() => onStatus(item, deprecated ? "confirm_fact" : "deprecate_fact")}>{deprecated ? <RotateCcw size={14} /> : <Trash2 size={14} />}</button></div></div>; })}{items.length === 0 && <div className="canon-empty">尚无记录</div>}</div></div>;
}

function EditorHeading({ title, onClose }: { title: string; onClose: () => void }) { return <div className="canon-editor-heading"><strong>{title}</strong><button type="button" title="关闭编辑" aria-label="关闭编辑" onClick={onClose}><X size={15} /></button></div>; }
function ReasonField({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <label>变更原因<textarea aria-label="变更原因" rows={4} value={value} onChange={(event) => onChange(event.target.value)} placeholder="说明为什么需要修改这条 Canon……" /></label>; }
function actionLabel(action: string) { return ({ upsert_fact: "保存事实", deprecate_fact: "废止事实", confirm_fact: "确认事实", merge_alias: "合并别名", update_character: "更新角色", upsert_thread: "保存叙事线程", update_thread_status: "更新线程状态", upsert_thread_beat: "保存叙事 beat" } as Record<string, string>)[action] ?? action; }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false }); }
function characterOperationPatch(patch: Record<string, string>): Record<string, unknown> {
  const relationships = patch.relationships.trim();
  if (!relationships) return { ...patch, relationships: [] };
  try { return { ...patch, relationships: JSON.parse(relationships) }; }
  catch { return { ...patch, relationships: relationships.split("\n").map((item) => item.trim()).filter(Boolean) }; }
}
