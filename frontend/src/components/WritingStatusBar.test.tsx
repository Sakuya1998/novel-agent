import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunJob } from "../types";
import { WritingStatusBar } from "./WritingStatusBar";

afterEach(cleanup);

const runningJob: RunJob = {
  id: "job-1",
  novel_id: "novel-1",
  action: "run",
  status: "running",
  request: {},
  current_node: "scene_writer",
  error: "",
  cancel_requested: false,
  created_at: "2026-09-17",
  updated_at: "2026-09-17",
};

const defaultProps = {
  job: null,
  connectionStatus: "idle" as const,
  currentChapter: 2,
  totalChapters: 8,
  disabled: false,
  onRun: vi.fn(),
  onCancel: vi.fn(),
  onRetry: vi.fn(),
};

describe("WritingStatusBar", () => {
  it("shows the current node and stop action while running", async () => {
    const onCancel = vi.fn();
    render(<WritingStatusBar
      {...defaultProps}
      status="running"
      job={runningJob}
      connectionStatus="polling"
      onCancel={onCancel}
    />);

    expect(screen.getByText("第 2 / 8 章")).toBeInTheDocument();
    expect(screen.getByText(/场景写作/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "停止运行" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("announces reconnecting without replacing the last known node", () => {
    render(<WritingStatusBar
      {...defaultProps}
      status="running"
      job={runningJob}
      connectionStatus="reconnecting"
    />);

    expect(screen.getByRole("status")).toHaveTextContent("连接中断，正在恢复");
    expect(screen.getByText(/场景写作/)).toBeInTheDocument();
  });

  it("offers one retry action when automatic reconnection has failed", async () => {
    const onRetry = vi.fn();
    render(<WritingStatusBar
      {...defaultProps}
      status="running"
      job={runningJob}
      connectionStatus="failed"
      onRetry={onRetry}
    />);

    expect(screen.getAllByRole("button")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("uses a single run action for resumable statuses", async () => {
    const onRun = vi.fn();
    const { rerender } = render(<WritingStatusBar
      {...defaultProps}
      status="idle"
      onRun={onRun}
    />);

    expect(screen.getAllByRole("button")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "开始创作" }));

    rerender(<WritingStatusBar
      {...defaultProps}
      status="interrupted"
      onRun={onRun}
    />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "继续运行" }));
    expect(onRun).toHaveBeenCalledTimes(2);
  });
});
