import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanonDialog } from "./CanonDialog";

const apiMocks = vi.hoisted(() => ({ getNovelCanon: vi.fn() }));

vi.mock("../api", () => apiMocks);

const canon = {
  version: 3,
  world_facts: [{ id: "world:1", path: "世界.城市", value: "雾都", source: "world_builder", status: "active" as const }],
  characters: { 林寒: { name: "林寒", role: "主角", personality: "谨慎", appearances: [1], last_seen_chapter: 1 } },
  aliases: {},
  timeline: [],
  facts: [],
  narrative_threads: [],
  audit: [],
};

describe("CanonDialog", () => {
  beforeEach(() => apiMocks.getNovelCanon.mockResolvedValue(canon));
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("requires a reason and submits a structured fact edit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<CanonDialog open novelId="novel_1" editable disabled={false} onClose={() => undefined} onSubmit={onSubmit} />);

    expect(await screen.findByText("世界.城市")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "编辑 世界.城市" }));
    const save = screen.getByRole("button", { name: "保存事实" });
    expect(save).toBeDisabled();
    await user.clear(screen.getByLabelText("事实内容"));
    await user.type(screen.getByLabelText("事实内容"), "新雾都");
    await user.type(screen.getByLabelText("变更原因"), "统一新版地名");
    await user.click(save);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      action: "upsert_fact",
      target_type: "world_fact",
      target_id: "world:1",
      path: "世界.城市",
      subject: undefined,
      kind: undefined,
      value: "新雾都",
      reason: "统一新版地名",
    }));
  });

  it("keeps mutation controls disabled outside human review", async () => {
    render(<CanonDialog open novelId="novel_1" editable={false} disabled={false} onClose={() => undefined} onSubmit={vi.fn()} />);
    expect(await screen.findByText("Canon 仅在章节人工审查阶段开放修改。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新增" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "编辑 世界.城市" })).toBeDisabled();
  });
});
