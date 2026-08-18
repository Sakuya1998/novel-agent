import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MemoryQualityHistory } from "../types";
import { MemoryQualityDialog } from "./MemoryQualityDialog";

afterEach(cleanup);

const history: MemoryQualityHistory = {
  latest: {
    id: 1,
    novel_id: "novel-1",
    mode: "evaluate",
    index_hash: "hash",
    created_at: "2026-08-18T08:00:00",
    report: {
      status: "passed",
      k: 5,
      case_count: 4,
      passed_cases: 4,
      index_record_count: 8,
      recall_at_k: 0.9,
      precision_at_k: 0.4,
      mrr: 0.8,
      stale_fact_hit_rate: 0.1,
      canon_vector_conflict_rate: 0,
    },
  },
  runs: [],
};

describe("MemoryQualityDialog", () => {
  it("shows retrieval metrics and runs rebuild", async () => {
    const onRebuild = vi.fn().mockResolvedValue({});
    render(<MemoryQualityDialog open history={history} onClose={vi.fn()} onRefresh={vi.fn().mockResolvedValue(history)} onEvaluate={vi.fn().mockResolvedValue({})} onRebuild={onRebuild} />);
    expect(screen.getByRole("dialog", { name: "长期记忆质量" })).toHaveTextContent("90.0%");
    expect(screen.getByRole("dialog", { name: "长期记忆质量" })).toHaveTextContent("0.80");
    await userEvent.click(screen.getByRole("button", { name: "重建并评测索引" }));
    expect(onRebuild).toHaveBeenCalledWith(true, 5);
  });
});
