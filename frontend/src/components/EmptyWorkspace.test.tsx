import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmptyWorkspace } from "./EmptyWorkspace";

afterEach(cleanup);

describe("EmptyWorkspace", () => {
  it("keeps the empty library operational with direct actions", async () => {
    const callbacks = { create: vi.fn(), import: vi.fn(), settings: vi.fn() };
    render(<EmptyWorkspace serviceStatus="ready" onCreate={callbacks.create} onImport={callbacks.import} onSettings={callbacks.settings} />);

    expect(screen.getByRole("heading", { name: "开始一个新故事" })).toBeInTheDocument();
    expect(screen.getByText("工作区已就绪")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /导入作品/ }));
    await userEvent.click(screen.getByRole("button", { name: /模型设置/ }));
    expect(callbacks.import).toHaveBeenCalledOnce();
    expect(callbacks.settings).toHaveBeenCalledOnce();
  });
});
