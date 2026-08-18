import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BookAuditReport } from "../types";
import { BookAuditPanel } from "./BookAuditPanel";

afterEach(cleanup);

const report: BookAuditReport = {
  schema_version: "book-audit-v1",
  rubric_version: "book-literary-audit-v1",
  manuscript_hash: "abc",
  deterministic_scores: { chapter_completion: 100, narrative_resolution: 65 },
  judge_scores: { plot_coherence: 88, ending_satisfaction: 82 },
  overall_score: 83.8,
  findings: [
    { dimension: "chapter_completion", score: 100, message: "章节完整", source: "deterministic" },
    { dimension: "literary_judgment", message: "结局完成主线承诺", source: "model" },
  ],
  revision_priorities: ["补强次要角色收束"],
};

describe("BookAuditPanel", () => {
  it("shows final scores, findings and revision priorities", () => {
    render(<BookAuditPanel report={report} totalChapters={2} onStartRevision={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "全书终审" })).toBeInTheDocument();
    expect(screen.getByText("83.8")).toBeInTheDocument();
    expect(screen.getAllByText("章节完整性")).toHaveLength(2);
    expect(screen.getByText("情节连贯")).toBeInTheDocument();
    expect(screen.getAllByText("补强次要角色收束")).toHaveLength(2);
    expect(screen.getByText("结局完成主线承诺")).toBeInTheDocument();
  });

  it("shows a degraded-mode warning", () => {
    render(<BookAuditPanel report={{ ...report, judge_scores: {}, judge_error: "模型终审失败:TimeoutError" }} totalChapters={2} onStartRevision={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("模型终审失败:TimeoutError");
  });

  it("starts a revision for the selected finalized chapter", async () => {
    const onStartRevision = vi.fn().mockResolvedValue(undefined);
    render(<BookAuditPanel report={report} totalChapters={3} onStartRevision={onStartRevision} />);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "章节" }), "2");
    const feedback = screen.getByRole("textbox", { name: "返修要求" });
    await userEvent.clear(feedback);
    await userEvent.type(feedback, "加强第二章与结局的因果连接");
    await userEvent.click(screen.getByRole("button", { name: "开始返修" }));

    expect(onStartRevision).toHaveBeenCalledWith(2, "加强第二章与结局的因果连接");
  });
});
