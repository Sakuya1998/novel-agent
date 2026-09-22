import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppErrorBoundary } from "./AppErrorBoundary";

function BrokenView(): never {
  throw new Error("render failed");
}

describe("AppErrorBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows a recoverable fallback when rendering fails", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("reportError", vi.fn());

    render(<AppErrorBoundary onReset={onReset}><BrokenView /></AppErrorBoundary>);

    expect(screen.getByRole("alert")).toHaveTextContent("工作台暂时无法显示");
    await user.click(screen.getByRole("button", { name: "重新加载工作台" }));
    expect(onReset).toHaveBeenCalledOnce();
  });
});
