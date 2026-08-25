import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NovelSidebar } from "./NovelSidebar";

describe("NovelSidebar creative brief", () => {
  afterEach(() => {
    cleanup();
    document.body.style.overflow = "";
    vi.restoreAllMocks();
  });

  it("submits structured creative constraints with a new novel", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(undefined);

    render(
      <NovelSidebar
        novels={[]}
        isLoading={false}
        isStreaming={false}
        onSelect={vi.fn()}
        onCreate={onCreate}
        onDelete={vi.fn()}
      />,
    );

    await user.click(screen.getByTitle("新建作品"));
    await user.type(screen.getByLabelText("标题"), "雾中剑");
    await user.type(screen.getByLabelText("一句话灵感"), "失忆剑客追查王印谜案");
    await user.click(screen.getByText("创作约束"));
    await user.clear(screen.getByLabelText("目标读者"));
    await user.type(screen.getByLabelText("目标读者"), "硬核推理读者");
    await user.selectOptions(screen.getByLabelText("叙事视角"), "first_person");
    await user.selectOptions(screen.getByLabelText("结局基调"), "bittersweet");
    await user.type(screen.getByLabelText("核心主题"), "身份，记忆，身份");
    await user.type(screen.getByLabelText("必须包含"), "公平线索；代价");
    await user.type(screen.getByLabelText("回避内容"), "无依据反转");
    fireEvent.change(screen.getByLabelText("悬疑强度"), { target: { value: "5" } });
    await user.click(screen.getByRole("button", { name: /开始创作/ }));

    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({
      title: "雾中剑",
      inspiration: "失忆剑客追查王印谜案",
      creative_brief: expect.objectContaining({
        target_audience: "硬核推理读者",
        age_rating: "teen",
        point_of_view: "first_person",
        ending_tone: "bittersweet",
        themes: ["身份", "记忆"],
        must_include: ["公平线索", "代价"],
        avoid_content: ["无依据反转"],
        intensity: expect.objectContaining({ mystery: 5 }),
      }),
    }));
  });

  it("keeps the dialog open and announces creation failures", async () => {
    const user = userEvent.setup();
    render(<NovelSidebar novels={[]} isLoading={false} isStreaming={false} onSelect={vi.fn()} onCreate={vi.fn().mockRejectedValue(new Error("标题已存在"))} onDelete={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "新建作品" }));
    await user.type(screen.getByLabelText("标题"), "重复作品");
    await user.type(screen.getByLabelText("一句话灵感"), "测试失败反馈");
    await user.click(screen.getByRole("button", { name: /开始创作/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("标题已存在");
    expect(screen.getByRole("dialog", { name: "创建一部新作品" })).toBeInTheDocument();
  });

  it("uses separate accessible controls for selecting and deleting a novel", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<NovelSidebar novels={[{ id: "novel-1", title: "孤城", genre: "武侠", total_chapters: 3, chapters: [] } as never]} selectedId="novel-1" isLoading={false} isStreaming={false} onSelect={onSelect} onCreate={vi.fn()} onDelete={onDelete} />);

    await user.click(screen.getByRole("button", { name: "打开《孤城》" }));
    expect(onSelect).toHaveBeenCalledWith("novel-1");
    await user.click(screen.getByRole("button", { name: "删除《孤城》" }));
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: "novel-1" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
