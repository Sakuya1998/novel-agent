import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunControlPanel } from "./RunControlPanel";

afterEach(cleanup);

describe("RunControlPanel", () => {
  it("shows the persisted node and cancels a running job", async () => {
    const onCancel = vi.fn();
    render(<RunControlPanel
      status="running"
      job={{
        id: "job-1",
        novel_id: "novel-1",
        action: "run",
        status: "running",
        request: {},
        current_node: "scene_writer",
        error: "",
        cancel_requested: false,
        created_at: "2026-08-17",
        updated_at: "2026-08-17",
      }}
      disabled={false}
      onRun={vi.fn()}
      onCancel={onCancel}
    />);

    expect(screen.getByText("当前节点：写作")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "停止运行" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("continues an interrupted checkpoint", async () => {
    const onRun = vi.fn();
    render(<RunControlPanel status="interrupted" job={null} disabled={false} onRun={onRun} onCancel={vi.fn()} />);

    expect(screen.getByText("检查点已经保存，可以从中断位置继续。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "继续运行" }));
    expect(onRun).toHaveBeenCalledOnce();
  });
});
