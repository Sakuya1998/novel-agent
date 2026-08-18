import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChapterEvaluation } from "../types";
import { ChapterEvaluationPanel } from "./ChapterEvaluationPanel";

afterEach(cleanup);

const versions = [
  { id: 1, chapter_number: 1, version_number: 1, source: "initial", word_count: 100, preview: "旧", created_at: "2026-08-17" },
  { id: 2, chapter_number: 1, version_number: 2, source: "revision", word_count: 110, preview: "新", created_at: "2026-08-17" },
];

function evaluation(overrides: Partial<ChapterEvaluation>): ChapterEvaluation {
  return {
    id: 1,
    novel_id: "novel-1",
    chapter_number: 1,
    version_number: 1,
    content_hash: "hash",
    evaluator_version: "chapter-quality-v1",
    rubric_version: "",
    model_provider: "",
    model_name: "",
    deterministic_scores: { structure: 80 },
    judge_scores: {},
    overall_score: 80,
    findings: [{ dimension: "structure", message: "结构完整", source: "deterministic" }],
    judge_error: "",
    is_baseline: false,
    created_at: "2026-08-17",
    ...overrides,
  };
}

describe("ChapterEvaluationPanel", () => {
  it("runs the selected model-assisted evaluation", async () => {
    const onEvaluate = vi.fn().mockResolvedValue(evaluation({ version_number: 2 }));
    render(<ChapterEvaluationPanel
      versions={versions}
      evaluations={[]}
      disabled={false}
      onEvaluate={onEvaluate}
      onSetBaseline={vi.fn()}
      onCompare={vi.fn()}
    />);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "评测模式" }), "judge");
    await userEvent.click(screen.getByRole("button", { name: "运行质量评测" }));

    expect(onEvaluate).toHaveBeenCalledWith(2, true);
  });

  it("sets a baseline and compares another version against it", async () => {
    const baseline = evaluation({ id: 1, version_number: 1, is_baseline: true });
    const candidate = evaluation({ id: 2, version_number: 2, overall_score: 84 });
    const onSetBaseline = vi.fn().mockResolvedValue(candidate);
    const onCompare = vi.fn().mockResolvedValue({
      from_evaluation_id: 1,
      to_evaluation_id: 2,
      from_version: 1,
      to_version: 2,
      overall_delta: 4,
      status: "improved",
      regression_threshold: 3,
      dimensions: {},
    });
    render(<ChapterEvaluationPanel
      versions={versions}
      evaluations={[candidate, baseline]}
      disabled={false}
      onEvaluate={vi.fn()}
      onSetBaseline={onSetBaseline}
      onCompare={onCompare}
    />);

    await userEvent.click(screen.getByRole("button", { name: "与基准 v1 比较" }));
    expect(onCompare).toHaveBeenCalledWith(1, 2);
    expect(await screen.findByText("质量提升")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "设为回归基准" }));
    expect(onSetBaseline).toHaveBeenCalledWith(2);
  });
});
