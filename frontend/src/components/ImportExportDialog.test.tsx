import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportExportDialog } from "./ImportExportDialog";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function preventNavigation() {
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-export");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
}

describe("ImportExportDialog", () => {
  it("starts an export with the selected format", async () => {
    preventNavigation();
    const onExport = vi.fn().mockResolvedValue({ blob: new Blob(["# test"]), filename: "test.md" });
    render(<ImportExportDialog open novelTitle="测试" onClose={vi.fn()} onExport={onExport} onImport={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText("导出格式"), "epub");
    await userEvent.click(screen.getByRole("button", { name: "导出文件" }));
    expect(onExport).toHaveBeenCalledWith("epub", "", { author: "", publisher: "", language: "zh-CN" });
  });

  it("passes a password only for encrypted backups", async () => {
    preventNavigation();
    const onExport = vi.fn().mockResolvedValue({ blob: new Blob(["PK"]), filename: "test.enc" });
    render(<ImportExportDialog open novelTitle="测试" onClose={vi.fn()} onExport={onExport} onImport={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText("导出格式"), "backup");
    await userEvent.type(screen.getByLabelText("导出备份密码"), "secret");
    await userEvent.click(screen.getByRole("button", { name: "导出文件" }));
    expect(onExport).toHaveBeenCalledWith("backup", "secret", { author: "", publisher: "", language: "zh-CN" });
  });

  it("renders inside a modal backdrop and disables export without a selected novel", () => {
    const { container } = render(<ImportExportDialog open novelTitle="" onClose={vi.fn()} onExport={vi.fn()} onImport={vi.fn()} />);

    expect(container.querySelector(".model-settings-backdrop")).toContainElement(screen.getByRole("dialog"));
    expect(screen.queryByRole("button", { name: "导出文件" })).not.toBeInTheDocument();
    expect(screen.getByText("请先从作品库选择一部作品，再进行导出。")).toBeInTheDocument();
  });

  it("imports the selected file with an optional title override", async () => {
    const user = userEvent.setup();
    const onImport = vi.fn().mockResolvedValue({});
    const file = new File(["# 第一章\n正文"], "draft.md", { type: "text/markdown" });
    render(<ImportExportDialog open novelTitle="" onClose={vi.fn()} onExport={vi.fn()} onImport={onImport} />);

    await user.upload(screen.getByLabelText("选择导入文件"), file);
    await user.type(screen.getByLabelText("导入后的标题"), "重命名作品");
    await user.type(screen.getByLabelText("导入备份密码"), "secret");
    await user.click(screen.getByRole("button", { name: "导入到当前工作区" }));

    expect(onImport).toHaveBeenCalledWith(file, "重命名作品", "secret");
    expect(screen.getByRole("status")).toHaveTextContent("导入完成");
  });
});
