import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelTrace } from "../types";
import { ModelTraceDialog } from "./ModelTraceDialog";

afterEach(cleanup);

const trace: ModelTrace = {
  id: 1,
  novel_id: "novel-1",
  agent: "scene_writer",
  purpose: "creative",
  provider: "openai",
  model_name: "gpt-test",
  attempt: 1,
  fallback_used: false,
  success: true,
  duration_ms: 120,
  input_tokens: 10,
  output_tokens: 20,
  usage_estimated: false,
  error_type: "",
  call_id: "call-1",
  trace_id: "trace-1",
  input_hash: "1234567890abcdef",
  output_hash: "abcdef1234567890",
  input_chars: 40,
  output_chars: 80,
  created_at: "2026-08-18T08:00:00",
};

describe("ModelTraceDialog", () => {
  it("shows trace metadata without raw model content", () => {
    render(<ModelTraceDialog open traces={[trace]} onRefresh={vi.fn().mockResolvedValue([])} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "模型调用轨迹" })).toHaveTextContent("scene_writer");
    expect(screen.getByRole("dialog", { name: "模型调用轨迹" })).toHaveTextContent("gpt-test");
    expect(screen.getByRole("dialog", { name: "模型调用轨迹" })).toHaveTextContent("1234567890");
    expect(screen.getByRole("dialog", { name: "模型调用轨迹" })).toHaveTextContent("不保存 Prompt、正文或 API Key");
  });

  it("reloads traces with the selected agent", async () => {
    const onRefresh = vi.fn().mockResolvedValue([]);
    render(<ModelTraceDialog open traces={[trace]} onRefresh={onRefresh} onClose={vi.fn()} />);

    await userEvent.selectOptions(screen.getByLabelText("筛选 Agent"), "scene_writer");
    expect(onRefresh).toHaveBeenCalledWith("scene_writer");
  });
});
