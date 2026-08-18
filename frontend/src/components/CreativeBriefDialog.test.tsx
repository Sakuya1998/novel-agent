import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDefaultCreativeBrief } from "../creativeBrief";
import type { CreativeBriefVersion } from "../types";
import { CreativeBriefDialog } from "./CreativeBriefDialog";

const versions: CreativeBriefVersion[] = [{
  id: 1,
  novel_id: "novel-1",
  version_number: 1,
  source: "created",
  change_summary: "初始创作约束",
  content_hash: "hash",
  created_at: "2026-08-18T09:00:00",
  creative_brief: createDefaultCreativeBrief(),
}];

describe("CreativeBriefDialog", () => {
  afterEach(() => cleanup());

  it("edits and submits a versioned brief", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const brief = createDefaultCreativeBrief();

    render(
      <CreativeBriefDialog
        open
        brief={brief}
        version={1}
        versions={versions}
        disabled={false}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    await user.clear(screen.getByLabelText("目标读者"));
    await user.type(screen.getByLabelText("目标读者"), "硬核推理读者");
    await user.selectOptions(screen.getByLabelText("叙事视角"), "first_person");
    await user.type(screen.getByLabelText("核心主题"), "身份，记忆");
    await user.type(screen.getByLabelText("本次修改说明"), "强化第一人称约束");
    fireEvent.change(screen.getByLabelText("悬疑强度"), { target: { value: "5" } });
    await user.click(screen.getByRole("button", { name: "保存约束" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      target_audience: "硬核推理读者",
      point_of_view: "first_person",
      themes: ["身份", "记忆"],
      intensity: expect.objectContaining({ mystery: 5 }),
    }), "强化第一人称约束");
  });

  it("keeps every field read-only while a run is active", () => {
    render(
      <CreativeBriefDialog
        open
        brief={createDefaultCreativeBrief()}
        version={2}
        versions={versions}
        disabled
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("目标读者").hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "保存约束" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("创作运行中，暂时只读").textContent).toContain("创作运行中，暂时只读");
  });
});
