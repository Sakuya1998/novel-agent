import { ArrowUpRight, Square } from "lucide-react";
import type { NovelStatus, RunJob } from "../types";
import { STAGES } from "../types";

interface Props {
  status: NovelStatus;
  job: RunJob | null;
  disabled: boolean;
  onRun: () => void;
  onCancel: () => void;
}

function nodeLabel(node?: string): string {
  return STAGES.find((stage) => stage.id === node)?.label ?? node ?? "准备中";
}

export function RunControlPanel({ status, job, disabled, onRun, onCancel }: Props) {
  const copy = status === "completed"
    ? { title: "这部作品已经完成", detail: "所有已生成章节都已定稿。" }
    : status === "running"
      ? { title: "后台任务正在运行", detail: `当前节点：${nodeLabel(job?.current_node)}` }
      : status === "interrupted"
        ? { title: "运行已中断", detail: "检查点已经保存，可以从中断位置继续。" }
        : status === "error"
          ? { title: "上次运行失败", detail: job?.error || "检查模型配置后可重新继续。" }
          : status === "legacy_read_only"
            ? { title: "只读作品", detail: "该作品缺少可恢复的运行检查点。" }
            : { title: "准备开始创作", detail: "将从世界观与角色设定开始。" };

  return <aside className="next-panel">
    <div className="section-kicker">RUN CONTROL</div>
    <h2>{copy.title}</h2>
    <p>{copy.detail}</p>
    {status === "running" ? <button className="secondary-button full-width stop-run-button" onClick={onCancel} disabled={disabled}><Square size={14} />停止运行</button> : null}
    {["idle", "interrupted", "error"].includes(status) ? <button className="primary-button full-width" onClick={onRun} disabled={disabled}>{status === "idle" ? "开始创作" : "继续运行"}<ArrowUpRight size={15} /></button> : null}
  </aside>;
}
