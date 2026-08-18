import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NarrativeThreadsPanel } from "./NarrativeThreadsPanel";

const threads = [{
  id: "thread:seal",
  title: "失踪王印",
  description: "追查王印去向",
  kind: "mystery",
  priority: "major" as const,
  status: "open" as const,
  introduced_chapter: 1,
  due_chapter: 4,
  resolved_chapter: null,
  beats: [{
    id: "thread:seal:beat:1",
    chapter: 1,
    action: "setup" as const,
    description: "发现空印盒",
    status: "completed" as const,
  }],
}];

afterEach(cleanup);

describe("NarrativeThreadsPanel", () => {
  it("submits a structured resolve beat with a mandatory reason", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<NarrativeThreadsPanel threads={threads} canMutate onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "新增 beat 失踪王印" }));
    await user.selectOptions(screen.getByLabelText("Beat 动作"), "resolve");
    await user.clear(screen.getByLabelText("Beat 章节"));
    await user.type(screen.getByLabelText("Beat 章节"), "4");
    await user.type(screen.getByLabelText("Beat 描述"), "揭示王印藏在剑鞘中");
    const save = screen.getByRole("button", { name: "保存 beat" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("线程变更原因"), "确定主线回收节点");
    await user.click(save);

    expect(onSubmit).toHaveBeenCalledWith({
      action: "upsert_thread_beat",
      target_id: "thread:seal",
      beat_id: undefined,
      chapter: 4,
      beat_action: "resolve",
      description: "揭示王印藏在剑鞘中",
      scene_number: undefined,
      reason: "确定主线回收节点",
    });
  });

  it("keeps all governance actions disabled in read-only mode", () => {
    render(<NarrativeThreadsPanel threads={threads} canMutate={false} onSubmit={vi.fn()} />);

    expect(screen.getByRole("button", { name: "新增线程" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "编辑线程 失踪王印" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "新增 beat 失踪王印" })).toBeDisabled();
  });
});
