import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlanningReviewPanel } from "./PlanningReviewPanel";

afterEach(cleanup);

describe("PlanningReviewPanel", () => {
  it.each(["stage", "novel"])("clears a previous submission error when the planning %s changes", async (changedScope) => {
    const props = {
      reviewScope: "novel-1:blueprint_review:1",
      reviewNode: "blueprint_review" as const,
      worldBible: "",
      characters: [], outline: [], scenePlan: [],
      disabled: false,
      onSubmit: vi.fn().mockRejectedValue(new Error("Old scope failed")),
    };
    const view = render(<PlanningReviewPanel {...props} />);
    await userEvent.type(screen.getByRole("textbox", { name: "世界观圣经" }), "Unsaved world");
    await userEvent.click(screen.getByRole("button", { name: "批准并继续" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Old scope failed");
    view.rerender(<PlanningReviewPanel {...props} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Old scope failed");
    expect(screen.getByRole("textbox", { name: "世界观圣经" })).toHaveValue("Unsaved world");

    view.rerender(<PlanningReviewPanel {...props}
      reviewScope={changedScope === "stage" ? "novel-1:scene_review:1" : "novel-2:blueprint_review:1"}
      reviewNode={changedScope === "stage" ? "scene_review" : "blueprint_review"}
    />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    if (changedScope === "novel") expect(screen.getByRole("textbox", { name: "世界观圣经" })).toHaveValue("Unsaved world");
  });

  it("ignores a rejected submission that settles after its planning scope changes", async () => {
    let reject!: (reason: Error) => void;
    const pending = new Promise<void>((_resolve, fail) => { reject = fail; });
    const props = {
      reviewScope: "novel-1:blueprint_review:1",
      reviewNode: "blueprint_review" as const,
      worldBible: "", characters: [], outline: [], scenePlan: [], disabled: false,
      onSubmit: vi.fn().mockReturnValue(pending),
    };
    const view = render(<PlanningReviewPanel {...props} />);
    await userEvent.click(screen.getByRole("button", { name: "批准并继续" }));
    view.rerender(<PlanningReviewPanel {...props} reviewScope="novel-2:blueprint_review:1" />);
    await act(async () => { reject(new Error("Old pending scope failed")); await pending.catch(() => undefined); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps planning edits and exposes a rejected resume command", async () => {
    render(<PlanningReviewPanel reviewNode="blueprint_review" worldBible="" characters={[]} outline={[]} scenePlan={[]} disabled={false} onSubmit={vi.fn().mockRejectedValue(new Error("resume unavailable"))} />);
    await userEvent.type(screen.getByRole("textbox", { name: "世界观圣经" }), "Keep this world");
    await userEvent.click(screen.getByRole("button", { name: "批准并继续" }));
    expect(screen.getByRole("alert")).toHaveTextContent("resume unavailable");
    expect(screen.getByRole("textbox", { name: "世界观圣经" })).toHaveValue("Keep this world");
    expect(screen.getByRole("button", { name: "批准并继续" })).toBeEnabled();
  });

  it("edits and submits the blueprint as structured data", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<PlanningReviewPanel
      reviewNode="blueprint_review"
      worldBible="城市: 雾都"
      characters={[{ name: "林寒", role: "主角", personality: "克制" }]}
      outline={[{ chapter: 1, title: "雾起", summary: "入城", estimated_words: 800 }]}
      scenePlan={[]}
      disabled={false}
      onSubmit={onSubmit}
    />);

    const name = screen.getByLabelText("角色 1 姓名");
    await userEvent.clear(name);
    await userEvent.type(name, "林霜");
    await userEvent.click(screen.getByRole("button", { name: "批准并继续" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      review_type: "blueprint_review",
      world_bible: "城市: 雾都",
      characters: [expect.objectContaining({ name: "林霜" })],
    }));
  });

  it("edits and submits the scene plan", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<PlanningReviewPanel
      reviewNode="scene_review"
      worldBible=""
      characters={[]}
      outline={[]}
      scenePlan={[{
        scene_number: 1,
        goal: "入城",
        conflict: "盘查",
        turn: "追兵现身",
        location: "城门",
        characters: ["林寒"],
        emotion: "紧张",
        estimated_words: 800,
      }]}
      disabled={false}
      onSubmit={onSubmit}
    />);

    const goal = screen.getByPlaceholderText("场景目标");
    await userEvent.clear(goal);
    await userEvent.type(goal, "潜入雾都");
    await userEvent.click(screen.getByRole("button", { name: "批准并继续" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      review_type: "scene_review",
      scene_plan: [expect.objectContaining({ goal: "潜入雾都" })],
    }));
  });

  it("compares versions and loads a historical blueprint into the editor", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onLoadVersion = vi.fn().mockResolvedValue({
      id: 1,
      novel_id: "n1",
      artifact_type: "blueprint",
      chapter_number: 0,
      version_number: 1,
      source: "generated",
      created_at: "2026-08-17T08:00:00",
      payload: {
        world_bible: "城市: 旧城",
        characters: [{ name: "旧名" }],
        outline: [{ chapter: 1, title: "旧章" }],
      },
    });
    const onCompareVersions = vi.fn().mockResolvedValue("- 城市: 旧城\n+ 城市: 新城");
    render(<PlanningReviewPanel
      reviewNode="blueprint_review"
      worldBible="城市: 新城"
      characters={[{ name: "新名" }]}
      outline={[{ chapter: 1, title: "新章" }]}
      scenePlan={[]}
      planningVersions={[
        { id: 1, novel_id: "n1", artifact_type: "blueprint", chapter_number: 0, version_number: 1, source: "generated", preview: "旧稿", created_at: "2026-08-17T08:00:00" },
        { id: 2, novel_id: "n1", artifact_type: "blueprint", chapter_number: 0, version_number: 2, source: "approved", preview: "新稿", created_at: "2026-08-17T09:00:00" },
      ]}
      disabled={false}
      onSubmit={onSubmit}
      onLoadVersion={onLoadVersion}
      onCompareVersions={onCompareVersions}
    />);

    await userEvent.click(screen.getByRole("button", { name: "比较" }));
    expect(onCompareVersions).toHaveBeenCalledWith(1, 2);
    expect(document.querySelector(".planning-version-diff")).toHaveTextContent("+ 城市: 新城");

    await userEvent.selectOptions(screen.getByLabelText("目标规划版本"), "1");
    await userEvent.click(screen.getByRole("button", { name: "回滚到此版本" }));
    expect(onLoadVersion).toHaveBeenCalledWith(1);
    expect(screen.getByLabelText("世界观圣经")).toHaveValue("城市: 旧城");
    expect(screen.getByLabelText("角色 1 姓名")).toHaveValue("旧名");
  });
});
