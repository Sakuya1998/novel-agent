import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvaluationBenchmarkRun } from "../types";
import { EvaluationBenchmarkDialog } from "./EvaluationBenchmarkDialog";

afterEach(cleanup);

const run: EvaluationBenchmarkRun = {
  id: "eval_1",
  suite_version: "novel-quality-benchmark-v1",
  evaluator_version: "chapter-quality-v1",
  rubric_version: "literary-judge-v1",
  prompt_hash: "prompt",
  input_hash: "input",
  include_judge: false,
  model_provider: "",
  model_name: "",
  baseline_run_id: null,
  gate_threshold: 70,
  regression_threshold: 3,
  overall_score: 94.3,
  status: "passed",
  judge_error: "",
  created_at: "2026-08-18T11:20:44",
  cases: [{
    id: "short",
    category: "short_chapter_quality",
    title: "短章结构与场景执行",
    input_hash: "case",
    minimum_score: 78,
    deterministic_scores: { structure: 90 },
    judge_scores: {},
    overall_score: 93,
    findings: [],
    judge_error: "",
    baseline_score: null,
    baseline_delta: null,
    regression_status: "not_compared",
    passed: true,
  }],
};

describe("EvaluationBenchmarkDialog", () => {
  it("shows history and runs against a selected baseline", async () => {
    const onRun = vi.fn().mockResolvedValue({ ...run, id: "eval_2" });
    render(<EvaluationBenchmarkDialog open runs={[run]} onRun={onRun} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "质量评测基准" })).toHaveTextContent("94.3");
    await userEvent.click(screen.getByRole("button", { name: "运行评测" }));
    expect(onRun).toHaveBeenCalledWith(false, "");
  });

  it("passes the model judge toggle", async () => {
    const onRun = vi.fn().mockResolvedValue(run);
    render(<EvaluationBenchmarkDialog open runs={[]} onRun={onRun} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "启用模型评审" }));
    await userEvent.click(screen.getByRole("button", { name: "运行评测" }));
    expect(onRun).toHaveBeenCalledWith(true, "");
  });
});
