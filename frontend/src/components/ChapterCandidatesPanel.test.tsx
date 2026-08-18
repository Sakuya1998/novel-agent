import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChapterCandidatesPanel } from "./ChapterCandidatesPanel";

afterEach(cleanup);

const candidate = {
  id: "candidate-1",
  generation_id: "job-1",
  novel_id: "novel-1",
  chapter_number: 1,
  candidate_number: 1,
  source_hash: "hash",
  instruction: "增强悬念",
  title: "雾起",
  content: "候选稿完整正文。",
  summary: "候选摘要",
  scene_plan: [],
  scene_drafts: [],
  scores: { structure: 92, repetition_control: 88 },
  overall_score: 90,
  evaluation_schema_version: "chapter-quality-v1",
  status: "available" as const,
  preview: "候选稿预览。",
  created_at: "2026-08-17",
};

describe("ChapterCandidatesPanel", () => {
  it("starts generation with the selected count and instruction", async () => {
    const onGenerate = vi.fn().mockResolvedValue(undefined);
    render(<ChapterCandidatesPanel
      candidates={[]}
      currentContent="当前稿"
      disabled={false}
      onGenerate={onGenerate}
      onSelect={vi.fn().mockResolvedValue(undefined)}
    />);

    await userEvent.click(screen.getByRole("button", { name: "4 稿" }));
    await userEvent.type(screen.getByLabelText("候选稿创作方向"), "增强悬念");
    await userEvent.click(screen.getByRole("button", { name: "生成候选稿" }));

    expect(onGenerate).toHaveBeenCalledWith(4, "增强悬念");
  });

  it("compares and selects a persisted candidate", async () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    render(<ChapterCandidatesPanel
      candidates={[candidate]}
      currentContent="当前稿完整正文。"
      disabled={false}
      onGenerate={vi.fn().mockResolvedValue(undefined)}
      onSelect={onSelect}
    />);

    expect(screen.getByText("90.0")).toBeInTheDocument();
    expect(screen.getByText("候选稿预览。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "对比" }));
    expect(screen.getByRole("dialog", { name: "候选稿对比" })).toHaveTextContent("当前稿完整正文。");
    expect(screen.getByRole("dialog", { name: "候选稿对比" })).toHaveTextContent("候选稿完整正文。");

    await userEvent.click(screen.getByRole("button", { name: "采用此稿" }));
    expect(onSelect).toHaveBeenCalledWith("candidate-1");
  });

  it("keeps stale candidates comparable but not selectable", () => {
    render(<ChapterCandidatesPanel
      candidates={[{ ...candidate, status: "stale" }]}
      currentContent="当前稿完整正文。"
      disabled={false}
      onGenerate={vi.fn().mockResolvedValue(undefined)}
      onSelect={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(screen.getByText("已过期")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "对比" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "需重新生成" }).hasAttribute("disabled")).toBe(true);
  });
});
