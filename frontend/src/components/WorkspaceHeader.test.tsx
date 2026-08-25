import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceHeader } from "./WorkspaceHeader";

afterEach(cleanup);

const actions = {
  onOpenAuth: vi.fn(),
  onOpenMonitoring: vi.fn(),
  onOpenBenchmarks: vi.fn(),
  onOpenImportExport: vi.fn(),
  onOpenTraces: vi.fn(),
  onOpenSettings: vi.fn(),
};

describe("WorkspaceHeader", () => {
  it("shows a non-interactive local workspace indicator when auth is disabled", () => {
    render(<WorkspaceHeader projectTitle="" authEnabled={false} authUser={null} {...actions} />);

    expect(screen.getByText("本地工作区")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
  });

  it("shows the login action only when auth is enabled", () => {
    render(<WorkspaceHeader projectTitle="" authEnabled authUser={null} {...actions} />);

    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
    expect(screen.queryByText("本地工作区")).not.toBeInTheDocument();
  });

  it("shows the actual backend readiness instead of a fixed healthy label", () => {
    const { rerender } = render(<WorkspaceHeader projectTitle="" serviceStatus="offline" authEnabled={false} authUser={null} {...actions} />);
    expect(screen.getByRole("status")).toHaveTextContent("服务未连接");

    rerender(<WorkspaceHeader projectTitle="" serviceStatus="degraded" authEnabled={false} authUser={null} {...actions} />);
    expect(screen.getByRole("status")).toHaveTextContent("服务需要关注");
  });

  it("supports keyboard navigation and restores focus when the tool menu closes", async () => {
    const user = userEvent.setup();
    render(<WorkspaceHeader projectTitle="" authEnabled={false} authUser={null} {...actions} />);
    const trigger = screen.getByRole("button", { name: "工具" });
    trigger.focus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menu", { name: "工作区工具" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /运行与审计/ })).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: /质量评测/ })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
