import { CheckCircle2, Edit3, GitBranch, Plus, Save, X } from "lucide-react";
import { useState } from "react";
import type { CanonOperation, NarrativeBeat, NarrativeBeatAction, NarrativeThread, NarrativeThreadStatus, ScenePlanItem } from "../types";

interface Props {
  threads: NarrativeThread[];
  canMutate: boolean;
  onSubmit: (operation: CanonOperation) => Promise<boolean>;
  currentChapter?: number;
  scenePlan?: ScenePlanItem[];
}

interface ThreadDraft {
  targetId?: string;
  title: string;
  description: string;
  kind: string;
  priority: "major" | "minor";
  introducedChapter: string;
  dueChapter: string;
}

interface BeatDraft {
  targetId: string;
  beatId?: string;
  threadTitle: string;
  chapter: string;
  action: NarrativeBeatAction;
  description: string;
  sceneNumber: string;
}

interface StatusDraft {
  targetId: string;
  threadTitle: string;
  status: NarrativeThreadStatus;
  resolvedChapter: string;
}

const blankThread = (): ThreadDraft => ({
  title: "",
  description: "",
  kind: "foreshadowing",
  priority: "minor",
  introducedChapter: "1",
  dueChapter: "",
});

export function NarrativeThreadsPanel({ threads, canMutate, onSubmit, currentChapter, scenePlan = [] }: Props) {
  const [threadDraft, setThreadDraft] = useState<ThreadDraft>();
  const [beatDraft, setBeatDraft] = useState<BeatDraft>();
  const [statusDraft, setStatusDraft] = useState<StatusDraft>();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  function reset() {
    setThreadDraft(undefined);
    setBeatDraft(undefined);
    setStatusDraft(undefined);
    setReason("");
  }

  function editThread(thread: NarrativeThread) {
    reset();
    setThreadDraft({
      targetId: thread.id,
      title: thread.title,
      description: thread.description,
      kind: thread.kind,
      priority: thread.priority,
      introducedChapter: String(thread.introduced_chapter),
      dueChapter: thread.due_chapter ? String(thread.due_chapter) : "",
    });
  }

  function editBeat(thread: NarrativeThread, beat?: NarrativeBeat) {
    reset();
    setBeatDraft({
      targetId: thread.id,
      beatId: beat?.id,
      threadTitle: thread.title,
      chapter: String(beat?.chapter ?? currentChapter ?? thread.due_chapter ?? thread.introduced_chapter),
      action: beat?.action ?? "develop",
      description: beat?.description ?? "",
      sceneNumber: beat?.scene_number ? String(beat.scene_number) : "",
    });
  }

  function editStatus(thread: NarrativeThread) {
    reset();
    setStatusDraft({
      targetId: thread.id,
      threadTitle: thread.title,
      status: thread.status,
      resolvedChapter: thread.resolved_chapter ? String(thread.resolved_chapter) : "",
    });
  }

  async function run(operation: CanonOperation) {
    setBusy(true);
    try {
      if (await onSubmit(operation)) reset();
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canMutate || busy;
  return <div className={`canon-layout ${threadDraft || beatDraft || statusDraft ? "with-editor" : ""}`}>
    <div className="canon-list-pane"><div className="canon-section">
      <div className="canon-toolbar"><div><strong>叙事线程</strong><span>{threads.filter((item) => ["planned", "open"].includes(item.status)).length} 条开放 · {threads.filter((item) => item.status === "resolved").length} 条已解决</span></div><button className="secondary-button" disabled={disabled} onClick={() => { reset(); setThreadDraft(blankThread()); }}><Plus size={14} />新增线程</button></div>
      <div className="narrative-thread-list">{threads.map((thread) => <div className={`narrative-thread-row ${thread.status}`} key={thread.id}>
        <div className="narrative-thread-heading"><span className={`thread-priority ${thread.priority}`}>{thread.priority === "major" ? "主线" : "支线"}</span><div><strong>{thread.title}</strong><p>{thread.description}</p></div><span className={`thread-status ${thread.status}`}>{statusLabel(thread.status)}</span><div className="canon-row-actions"><button title="编辑线程" aria-label={`编辑线程 ${thread.title}`} disabled={disabled} onClick={() => editThread(thread)}><Edit3 size={14} /></button><button title="更新状态" aria-label={`更新状态 ${thread.title}`} disabled={disabled} onClick={() => editStatus(thread)}><CheckCircle2 size={14} /></button><button title="新增 beat" aria-label={`新增 beat ${thread.title}`} disabled={disabled} onClick={() => editBeat(thread)}><Plus size={14} /></button></div></div>
        <div className="narrative-thread-meta"><span>引入 第 {thread.introduced_chapter} 章</span><span>截止 {thread.due_chapter ? `第 ${thread.due_chapter} 章` : "未设定"}</span>{thread.resolved_chapter ? <span>解决 第 {thread.resolved_chapter} 章</span> : null}</div>
        <div className="narrative-beat-list">{thread.beats.map((beat) => <button type="button" key={beat.id} disabled={disabled} onClick={() => editBeat(thread, beat)}><span>{String(beat.chapter).padStart(2, "0")}</span><strong>{actionLabel(beat.action)}</strong><p>{beat.description}</p><em>{beat.status === "completed" ? "已完成" : "计划"}</em></button>)}{thread.beats.length === 0 && <span className="narrative-no-beats">尚未安排逐章 beat</span>}</div>
      </div>)}{threads.length === 0 && <div className="canon-empty">尚无叙事线程</div>}</div>
    </div></div>
    {threadDraft && <form className="canon-editor-pane" onSubmit={(event) => { event.preventDefault(); void run({ action: "upsert_thread", target_id: threadDraft.targetId, title: threadDraft.title.trim(), description: threadDraft.description.trim(), kind: threadDraft.kind.trim(), priority: threadDraft.priority, introduced_chapter: Number(threadDraft.introducedChapter), due_chapter: threadDraft.dueChapter ? Number(threadDraft.dueChapter) : null, reason: reason.trim() }); }}><EditorTitle title={threadDraft.targetId ? "编辑叙事线程" : "新增叙事线程"} onClose={reset} /><label>标题<input aria-label="线程标题" value={threadDraft.title} onChange={(event) => setThreadDraft({ ...threadDraft, title: event.target.value })} /></label><label>说明<textarea aria-label="线程说明" rows={5} value={threadDraft.description} onChange={(event) => setThreadDraft({ ...threadDraft, description: event.target.value })} /></label><label>类型<select aria-label="线程类型" value={threadDraft.kind} onChange={(event) => setThreadDraft({ ...threadDraft, kind: event.target.value })}><option value="foreshadowing">伏笔</option><option value="mystery">谜团</option><option value="quest">任务</option><option value="relationship">关系</option><option value="promise">叙事承诺</option></select></label><label>优先级<select aria-label="线程优先级" value={threadDraft.priority} onChange={(event) => setThreadDraft({ ...threadDraft, priority: event.target.value as "major" | "minor" })}><option value="major">主线</option><option value="minor">支线</option></select></label><div className="canon-form-columns"><label>引入章节<input aria-label="引入章节" type="number" min="1" value={threadDraft.introducedChapter} onChange={(event) => setThreadDraft({ ...threadDraft, introducedChapter: event.target.value })} /></label><label>截止章节<input aria-label="截止章节" type="number" min="1" value={threadDraft.dueChapter} onChange={(event) => setThreadDraft({ ...threadDraft, dueChapter: event.target.value })} /></label></div><Reason value={reason} onChange={setReason} /><button className="primary-button" disabled={disabled || !threadDraft.title.trim() || !threadDraft.introducedChapter || !reason.trim()}><Save size={14} />保存线程</button></form>}
    {beatDraft && <form className="canon-editor-pane" onSubmit={(event) => { event.preventDefault(); void run({ action: "upsert_thread_beat", target_id: beatDraft.targetId, beat_id: beatDraft.beatId, chapter: Number(beatDraft.chapter), beat_action: beatDraft.action, description: beatDraft.description.trim(), scene_number: beatDraft.sceneNumber ? Number(beatDraft.sceneNumber) : undefined, reason: reason.trim() }); }}><EditorTitle title={`${beatDraft.beatId ? "编辑" : "新增"} beat`} onClose={reset} /><div className="canon-target-summary"><GitBranch size={14} /> {beatDraft.threadTitle}</div><label>章节<input aria-label="Beat 章节" type="number" min="1" value={beatDraft.chapter} onChange={(event) => setBeatDraft({ ...beatDraft, chapter: event.target.value })} /></label><label>动作<select aria-label="Beat 动作" value={beatDraft.action} onChange={(event) => setBeatDraft({ ...beatDraft, action: event.target.value as NarrativeBeatAction })}><option value="setup">埋设</option><option value="develop">推进</option><option value="resolve">回收</option></select></label>{Number(beatDraft.chapter) === currentChapter && scenePlan.length > 0 ? <label>承载场景<select aria-label="Beat 承载场景" value={beatDraft.sceneNumber} onChange={(event) => setBeatDraft({ ...beatDraft, sceneNumber: event.target.value })}><option value="">自动选择首场</option>{scenePlan.map((scene) => <option key={scene.scene_number} value={scene.scene_number}>第 {scene.scene_number} 场 · {scene.goal}</option>)}</select></label> : null}<label>描述<textarea aria-label="Beat 描述" rows={6} value={beatDraft.description} onChange={(event) => setBeatDraft({ ...beatDraft, description: event.target.value })} /></label><Reason value={reason} onChange={setReason} /><button className="primary-button" disabled={disabled || !beatDraft.chapter || !beatDraft.description.trim() || !reason.trim()}><Save size={14} />保存 beat</button></form>}
    {statusDraft && <form className="canon-editor-pane" onSubmit={(event) => { event.preventDefault(); void run({ action: "update_thread_status", target_id: statusDraft.targetId, status: statusDraft.status, resolved_chapter: statusDraft.status === "resolved" ? Number(statusDraft.resolvedChapter) : undefined, reason: reason.trim() }); }}><EditorTitle title="更新线程状态" onClose={reset} /><div className="canon-target-summary">{statusDraft.threadTitle}</div><label>状态<select aria-label="线程状态" value={statusDraft.status} onChange={(event) => setStatusDraft({ ...statusDraft, status: event.target.value as NarrativeThreadStatus })}><option value="planned">计划中</option><option value="open">开放</option><option value="resolved">已解决</option><option value="abandoned">已放弃</option></select></label>{statusDraft.status === "resolved" && <label>解决章节<input aria-label="解决章节" type="number" min="1" value={statusDraft.resolvedChapter} onChange={(event) => setStatusDraft({ ...statusDraft, resolvedChapter: event.target.value })} /></label>}<Reason value={reason} onChange={setReason} /><button className="primary-button" disabled={disabled || !reason.trim() || (statusDraft.status === "resolved" && !statusDraft.resolvedChapter)}><CheckCircle2 size={14} />保存状态</button></form>}
  </div>;
}

function EditorTitle({ title, onClose }: { title: string; onClose: () => void }) { return <div className="canon-editor-heading"><strong>{title}</strong><button type="button" title="关闭编辑" aria-label="关闭线程编辑" onClick={onClose}><X size={15} /></button></div>; }
function Reason({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <label>变更原因<textarea aria-label="线程变更原因" rows={4} value={value} onChange={(event) => onChange(event.target.value)} /></label>; }
function statusLabel(status: NarrativeThreadStatus) { return ({ planned: "计划中", open: "开放", resolved: "已解决", abandoned: "已放弃" })[status]; }
function actionLabel(action: NarrativeBeatAction) { return ({ setup: "埋设", develop: "推进", resolve: "回收" })[action]; }
