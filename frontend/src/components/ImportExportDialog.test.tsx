import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportExportDialog } from "./ImportExportDialog";

afterEach(cleanup);

describe("ImportExportDialog", () => {
  it("starts an export with the selected format", async () => {
    const onExport = vi.fn().mockResolvedValue({ blob: new Blob(["# test"]), filename: "test.md" });
    render(<ImportExportDialog open novelTitle="测试" onClose={vi.fn()} onExport={onExport} onImport={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText("导出格式"), "epub");
    await userEvent.click(screen.getByRole("button", { name: "导出文件" }));
    expect(onExport).toHaveBeenCalledWith("epub", "", { author: "", publisher: "", language: "zh-CN" });
  });

  it("passes a password only for encrypted backups", async () => {
    const onExport = vi.fn().mockResolvedValue({ blob: new Blob(["PK"]), filename: "test.enc" });
    render(<ImportExportDialog open novelTitle="测试" onClose={vi.fn()} onExport={onExport} onImport={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText("导出格式"), "backup");
    await userEvent.type(screen.getByLabelText("导出备份密码"), "secret");
    await userEvent.click(screen.getByRole("button", { name: "导出文件" }));
    expect(onExport).toHaveBeenCalledWith("backup", "secret", { author: "", publisher: "", language: "zh-CN" });
  });
});
