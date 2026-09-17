import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChapterCandidate, ChapterEvaluation, ChapterVersion, ConflictExplanation, Draft, ReviewSubmission, ScenePlanItem } from "../types";
import { ReviewWorkspace } from "./ReviewWorkspace";

afterEach(cleanup);

const scenePlan: ScenePlanItem[] = [{
  scene_number: 2,
  goal: "摆脱追兵",
  conflict: "道路封锁",
  turn: "进入暗巷",
  location: "长街",
  characters: ["林寒"],
  emotion: "急迫",
  estimated_words: 600,
}];

const draft: Draft = {
  chapter_number: 2,
  title: "雾都",
  content: "当前稿",
  scene_plan: scenePlan,
};

const candidate: ChapterCandidate = {
  id: "candidate-1",
  generation_id: "job-1",
  novel_id: "novel-1",
  chapter_number: 2,
  candidate_number: 1,
  source_hash: "hash",
  instruction: "增强悬念",
  title: "雾都",
  content: "候选稿",
  scene_plan: [],
  scene_drafts: [],
  scores: { structure: 92 },
  overall_score: 90,
  evaluation_schema_version: "chapter-quality-v1",
  status: "available",
  preview: "候选稿",
  created_at: "2026-08-17",
};

const version: ChapterVersion = { id: 1, chapter_number: 2, version_number: 1, source: "initial", word_count: 10, preview: "初稿", created_at: "2026-08-17" };
const conflict: ConflictExplanation = {
  conflict_id: "conflict-1",
  type: "timeline",
  title: "时间线冲突",
  severity: "high",
  description: "人物在同一时刻出现在两处",
  evidence: [{ label: "章节 1", value: "城门" }],
  conflicting_records: [],
  impact: "会削弱因果关系",
  repair_options: [{ id: "repair-1", label: "按建议返修", kind: "revision_feedback", feedback: "修正时间线" }],
};

function renderWorkspace(overrides: Partial<React.ComponentProps<typeof ReviewWorkspace>> = {}) {
  const onSubmit = vi.fn<(review: ReviewSubmission) => Promise<void>>().mockResolvedValue(undefined);
  const props: React.ComponentProps<typeof ReviewWorkspace> = {
    novelId: "novel-1",
    draft,
    issues: [],
    persistenceError: "",
    disabled: false,
    onSubmit,
    onGenerateCandidates: vi.fn().mockResolvedValue(undefined),
    onCompareVersions: vi.fn().mockResolvedValue(""),
    ...overrides,
  };
  render(<ReviewWorkspace {...props} />);
  return { props, onSubmit };
}

describe("ReviewWorkspace", () => {
  it("switches among decision, issues, candidates, and versions", async () => {
    renderWorkspace({
      issues: [{ type: "consistency", description: "时间线冲突", severity: "high" }],
      candidates: [],
      versions: [{ id: 1, chapter_number: 2, version_number: 1, source: "initial", word_count: 10, preview: "初稿", created_at: "2026-08-17" }],
    });

    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: /候选稿/ }));
    expect(screen.getByRole("tabpanel", { name: /候选稿/ })).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: /版本/ }));
    expect(screen.getByRole("tabpanel", { name: /版本/ })).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: /问题/ }));
    expect(screen.getByRole("tabpanel", { name: /问题/ })).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: /决定/ }));
    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeVisible();
  });

  it("selects a scene and submits scene-scoped feedback", async () => {
    const { props, onSubmit } = renderWorkspace();

    await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "第 2 场修改意见" }), "增强转折");
    await userEvent.click(screen.getByRole("button", { name: "重写此场景" }));

    expect(onSubmit).toHaveBeenCalledWith({ feedback: "增强转折", scene_number: 2 });
    expect(props.onSubmit).toHaveBeenCalledWith({ feedback: "增强转折", scene_number: 2 });
  });

  it("returns to the decision tab after a candidate replaces the draft", async () => {
    const onFocusReader = vi.fn();
    const { onSubmit } = renderWorkspace({ candidates: [candidate], onFocusReader });

    await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
    await userEvent.click(screen.getByRole("tab", { name: /候选稿/ }));
    await userEvent.click(screen.getByRole("button", { name: "采用此稿" }));

    expect(onSubmit).toHaveBeenCalledWith({ feedback: "candidate", candidate_id: "candidate-1" });
    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeVisible();
    expect(onFocusReader).toHaveBeenCalledWith(2, 1);
  });

  it("returns to the decision tab after a version is restored", async () => {
    const onFocusReader = vi.fn();
    const { onSubmit } = renderWorkspace({ versions: [version], onFocusReader });

    await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
    await userEvent.click(screen.getByRole("tab", { name: /版本/ }));
    await userEvent.click(screen.getByRole("button", { name: "恢复 v1" }));

    expect(onSubmit).toHaveBeenCalledWith({ feedback: "restore", version_number: 1 });
    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeVisible();
    expect(onFocusReader).toHaveBeenCalledWith(2, 1);
  });

  it("preserves conflict evidence, repair actions, and quality gate in the issues tab", async () => {
    const { onSubmit } = renderWorkspace({
      conflicts: [conflict],
      qualityReport: { overall_score: 68, threshold: 70, passed: false, status: "escalated", findings: [{ dimension: "pacing", score: 55, message: "场景推进偏慢" }] },
    });

    await userEvent.click(screen.getByRole("tab", { name: /问题/ }));
    expect(screen.getByText("转人工")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "查看证据与建议" }));
    expect(screen.getByText("章节 1")).toBeInTheDocument();
    expect(screen.getByText("会削弱因果关系")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "按建议返修" }));
    expect(onSubmit).toHaveBeenCalledWith({ feedback: "修正时间线" });
  });

  it("shows the versions tab and active error when candidate adoption rejects", async () => {
    const failure = new Error("candidate unavailable");
    const onSubmit = vi.fn().mockRejectedValue(failure);
    const onFocusReader = vi.fn();
    renderWorkspace({ candidates: [candidate], onSubmit, onFocusReader });

    await userEvent.click(screen.getByRole("tab", { name: /候选稿/ }));
    await userEvent.click(screen.getByRole("button", { name: "采用此稿" }));

    expect(screen.getByRole("alert")).toHaveTextContent("candidate unavailable");
    expect(screen.getByRole("tabpanel", { name: /候选稿/ })).toBeVisible();
    expect(onFocusReader).not.toHaveBeenCalled();
  });

  it("keeps a rejected issue repair on the issues tab and exposes its error", async () => {
    const failure = new Error("repair unavailable");
    const onSubmit = vi.fn().mockRejectedValue(failure);
    renderWorkspace({ conflicts: [conflict], onSubmit });

    await userEvent.click(screen.getByRole("tab", { name: /问题/ }));
    await userEvent.click(screen.getByRole("button", { name: "查看证据与建议" }));
    await userEvent.click(screen.getByRole("button", { name: "按建议返修" }));

    expect(screen.getByRole("alert")).toHaveTextContent("repair unavailable");
    expect(screen.getByRole("tabpanel", { name: /问题/ })).toBeVisible();
  });

  it("shows versions when evaluation data exists without snapshots", async () => {
    const evaluation: ChapterEvaluation = {
      id: 1,
      novel_id: "novel-1",
      chapter_number: 2,
      version_number: 1,
      content_hash: "hash",
      evaluator_version: "rules-1",
      rubric_version: "rubric-1",
      model_provider: "",
      model_name: "",
      deterministic_scores: { pacing: 80 },
      judge_scores: {},
      overall_score: 80,
      findings: [],
      judge_error: "",
      is_baseline: false,
      created_at: "2026-08-17",
    };
    renderWorkspace({
      evaluations: [evaluation],
      onEvaluateVersion: vi.fn().mockResolvedValue(evaluation),
      onSetEvaluationBaseline: vi.fn().mockResolvedValue(evaluation),
      onCompareEvaluations: vi.fn().mockResolvedValue({ status: "stable", overall_delta: 0 }),
    });

    await userEvent.click(screen.getByRole("tab", { name: /版本/ }));
    expect(screen.getByText("质量评测")).toBeInTheDocument();
    expect(screen.getByText("80.0")).toBeInTheDocument();
    expect(screen.getByText("暂无可用版本")).toBeInTheDocument();
  });

  it("shows versions when version commands exist without snapshots", async () => {
    renderWorkspace({ onCompareVersions: vi.fn().mockResolvedValue(""), versions: [] });

    expect(screen.getByRole("tab", { name: /版本/ })).toBeInTheDocument();
  });

  it("hides versions when neither data nor version commands exist", () => {
    renderWorkspace({ onGenerateCandidates: undefined, onCompareVersions: undefined, versions: [], evaluations: [] });

    expect(screen.queryByRole("tab", { name: /版本/ })).not.toBeInTheDocument();
  });
});
