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
  it("shows the final audit as the current node after the novel completes", () => {
    render(<WritingStatusBar {...defaultProps} status="completed" />);

    expect(screen.getByText("全书终审")).toBeInTheDocument();
    expect(screen.queryByText("准备中")).not.toBeInTheDocument();
  });

  it.each([undefined, ""])("shows a placeholder when both node sources are empty (%s)", (lastNode) => {
    render(<WritingStatusBar {...defaultProps} status="running" job={{ ...runningJob, current_node: "" }} lastNode={lastNode} />);
    expect(screen.getByText("准备中")).toBeInTheDocument();
  });

  it("falls back to the last event node when the persisted node is empty", () => {
    render(<WritingStatusBar {...defaultProps} status="running" job={{ ...runningJob, current_node: "" }} lastNode="scene_writer" />);
    expect(screen.getByText("场景写作")).toBeInTheDocument();
  });

  it("prefers the persisted node over the last event", () => {
    render(<WritingStatusBar {...defaultProps} status="running" job={runningJob} lastNode="unknown_node" />);
    expect(screen.getByText("场景写作")).toBeInTheDocument();
    expect(screen.queryByText("unknown_node")).not.toBeInTheDocument();
  });

  it("disables cancellation after a stop request", () => {
    render(<WritingStatusBar {...defaultProps} status="running" job={{ ...runningJob, cancel_requested: true }} />);
    expect(screen.getByRole("button", { name: "正在停止" })).toBeDisabled();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it.each(["human_review", "blueprint_review", "scene_review", "completed", "legacy_read_only"] as const)("has no run command for %s", (status) => {
    render(<WritingStatusBar {...defaultProps} status={status} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("resumes errors and respects disabled commands", () => {
    render(<WritingStatusBar {...defaultProps} status="error" disabled />);
    expect(screen.getByRole("button", { name: "继续运行" })).toBeDisabled();
  });

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
