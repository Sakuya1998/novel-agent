import { ArrowUpRight, RotateCcw, Square } from "lucide-react";
import type { NovelStatus, RunJob, WorkflowStage } from "../types";
import { STAGES } from "../types";
import type { RunConnectionStatus } from "../useRunJob";

interface Props {
  status: NovelStatus;
  job: RunJob | null;
  connectionStatus: RunConnectionStatus;
  currentChapter: number;
  totalChapters: number;
  disabled: boolean;
  onRun: () => void;
  onCancel: () => void;
  onRetry: () => void;
}

const STATUS_COPY: Record<NovelStatus, { label: string; detail: string }> = {
  idle: { label: "准备开始", detail: "从世界观与角色设定开始" },
  running: { label: "创作进行中", detail: "后台任务正在执行" },
  interrupted: { label: "运行已中断", detail: "可从检查点继续" },
  blueprint_review: { label: "等待蓝图审阅", detail: "确认设定后继续" },
  scene_review: { label: "等待分镜审阅", detail: "确认场景计划后继续" },
  human_review: { label: "等待章节审稿", detail: "决定返修或通过定稿" },
  completed: { label: "创作完成", detail: "全部章节已定稿" },
  error: { label: "运行失败", detail: "检查错误后重新继续" },
  legacy_read_only: { label: "只读作品", detail: "缺少可恢复检查点" },
};

const CONNECTION_COPY: Record<RunConnectionStatus, string> = {
  idle: "等待运行",
  polling: "运行状态已连接",
  reconnecting: "连接中断，正在恢复",
  failed: "连接失败，请重新连接",
};

function nodeLabel(node?: string): string {
  const stage: WorkflowStage | undefined = STAGES.find((item) => item.id === node);
  return stage?.statusLabel ?? stage?.label ?? node ?? "准备中";
}

export function WritingStatusBar({
  status,
  job,
  connectionStatus,
  currentChapter,
  totalChapters,
  disabled,
  onRun,
  onCancel,
  onRetry,
}: Props) {
  const copy = STATUS_COPY[status];
  const stopping = status === "running" && Boolean(job?.cancel_requested);

  let action = null;
  if (connectionStatus === "failed") {
    action = <button className="secondary-button writing-status-action" onClick={onRetry} disabled={disabled}>
      <RotateCcw size={14} />重新连接
    </button>;
  } else if (status === "running") {
    action = <button className="secondary-button stop-run-button writing-status-action" onClick={onCancel} disabled={disabled || stopping}>
      <Square size={14} />{stopping ? "正在停止" : "停止运行"}
    </button>;
  } else if (["idle", "interrupted", "error"].includes(status)) {
    action = <button className="primary-button writing-status-action" onClick={onRun} disabled={disabled}>
      {status === "idle" ? "开始创作" : "继续运行"}<ArrowUpRight size={15} />
    </button>;
  }

  return (
    <section className={`writing-status-bar status-${status}`} aria-label="创作状态">
      <div className="writing-status-progress">
        <span>章节进度</span>
        <strong>第 {currentChapter} / {totalChapters} 章</strong>
      </div>
      <div className="writing-status-summary">
        <span>{copy.label}</span>
        <strong>{copy.detail}</strong>
      </div>
      <div className="writing-status-node">
        <span>当前节点</span>
        <strong>{nodeLabel(job?.current_node)}</strong>
      </div>
      <div className="writing-status-connection">
        <span className={`status-dot ${connectionStatus}`} aria-hidden="true" />
        <span role="status" aria-live="polite">{CONNECTION_COPY[connectionStatus]}</span>
      </div>
      <div className="writing-status-command">{action}</div>
    </section>
  );
}
