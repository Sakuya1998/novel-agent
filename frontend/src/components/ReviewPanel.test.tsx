import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewPanel } from "./ReviewPanel";

afterEach(cleanup);

describe("ReviewPanel", () => {
  it("shows the scene plan and submits approval", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewPanel
      draft={{
        chapter_number: 1,
        scene_plan: [{
          scene_number: 1,
          goal: "进入雾都",
          conflict: "城门盘查",
          turn: "发现追兵",
          location: "城门",
          characters: ["林寒"],
          emotion: "紧张",
          estimated_words: 800,
        }],
      }}
      issues={[]}
      persistenceError=""
      disabled={false}
      onSubmit={onSubmit}
    />);

    expect(screen.getByText("修改范围")).toBeInTheDocument();
    expect(screen.getByText("进入雾都")).toBeInTheDocument();
    expect(screen.getByText("城门 · 紧张 · 800 字")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "通过定稿" }));
    expect(onSubmit).toHaveBeenCalledWith({ feedback: "approve" });
  });

  it("submits feedback for the selected scene only", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewPanel
      draft={{
        chapter_number: 1,
        scene_plan: [{
          scene_number: 2,
          goal: "摆脱追兵",
          conflict: "道路封锁",
          turn: "进入暗巷",
          location: "长街",
          characters: ["林寒"],
          emotion: "急迫",
          estimated_words: 600,
        }],
      }}
      issues={[]}
      persistenceError=""
      disabled={false}
      onSubmit={onSubmit}
    />);

    await userEvent.click(screen.getByRole("button", { name: /摆脱追兵/ }));
    await userEvent.type(screen.getByLabelText("第 2 场修改意见"), "加强动作冲突");
    await userEvent.click(screen.getByRole("button", { name: "重写此场景" }));

    expect(onSubmit).toHaveBeenCalledWith({
      feedback: "加强动作冲突",
      scene_number: 2,
    });
  });

  it("shows the automatic quality gate report", () => {
    render(<ReviewPanel
      draft={{ chapter_number: 1 }}
      issues={[]}
      qualityReport={{
        overall_score: 68,
        threshold: 70,
        passed: false,
        status: "escalated",
        findings: [{ dimension: "pacing", score: 55, message: "场景推进偏慢" }],
      }}
      persistenceError=""
      disabled={false}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(screen.getByText("自动质量门")).toBeInTheDocument();
    expect(screen.getByText("转人工")).toBeInTheDocument();
    expect(screen.getByText(/场景推进偏慢/)).toBeInTheDocument();
  });
});
