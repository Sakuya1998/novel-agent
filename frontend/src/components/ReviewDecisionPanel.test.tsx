import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScenePlanItem } from "../types";
import { ReviewDecisionPanel } from "./ReviewDecisionPanel";

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

function renderPanel(overrides: Partial<React.ComponentProps<typeof ReviewDecisionPanel>> = {}) {
  const props: React.ComponentProps<typeof ReviewDecisionPanel> = {
    scenePlan,
    sceneNumber: undefined,
    feedback: "",
    busyAction: "",
    disabled: false,
    error: "",
    onSceneChange: vi.fn(),
    onFeedbackChange: vi.fn(),
    onRevise: vi.fn().mockResolvedValue(undefined),
    onApprove: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  render(<ReviewDecisionPanel {...props} />);
  return props;
}

describe("ReviewDecisionPanel", () => {
  it("labels whole-chapter feedback and disables a blank revision", () => {
    renderPanel({ feedback: "   " });

    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "重写整章" })).toBeDisabled();
  });

  it("labels scene feedback and forwards controlled decision callbacks", async () => {
    const props = renderPanel({ sceneNumber: 2, feedback: "增强动作冲突" });

    const feedback = screen.getByRole("textbox", { name: "第 2 场修改意见" });
    await userEvent.type(feedback, "!");
    await userEvent.click(screen.getByRole("button", { name: "重写此场景" }));
    await userEvent.click(screen.getByRole("button", { name: "通过定稿" }));

    expect(props.onFeedbackChange).toHaveBeenCalledWith("增强动作冲突!");
    expect(props.onRevise).toHaveBeenCalledOnce();
    expect(props.onApprove).toHaveBeenCalledOnce();
  });

  it("offers whole-chapter and scene scope controls", async () => {
    const props = renderPanel({ sceneNumber: 2 });

    await userEvent.click(screen.getByRole("button", { name: "整章修改" }));
    await userEvent.click(screen.getByRole("button", { name: /第 2 场.*摆脱追兵/ }));

    expect(props.onSceneChange).toHaveBeenNthCalledWith(1, undefined);
    expect(props.onSceneChange).toHaveBeenNthCalledWith(2, 2);
  });

  it("disables every decision control while busy and exposes the error", () => {
    renderPanel({ feedback: "收紧节奏", busyAction: "revision", error: "service unavailable" });

    expect(screen.getByRole("alert")).toHaveTextContent("service unavailable");
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "重写中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "通过定稿" })).toBeDisabled();
  });
});
