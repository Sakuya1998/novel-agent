import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthSession } from "../types";
import { AuthDialog } from "./AuthDialog";

afterEach(cleanup);

const session: AuthSession = {
  access_token: "token",
  token_type: "bearer",
  expires_at: "2026-09-18T00:00:00Z",
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "alice",
    email: "alice@example.test",
    display_name: "Alice",
    role: "owner",
    tenant_name: "Alice 工作区",
  },
};

describe("AuthDialog", () => {
  it("submits login credentials", async () => {
    const onLogin = vi.fn().mockResolvedValue(session);
    render(<AuthDialog open currentUser={null} onLogin={onLogin} onRegister={vi.fn()} onLogout={vi.fn()} onClose={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("用户名或邮箱"), "alice");
    await userEvent.type(screen.getByLabelText("密码"), "password-1");
    await userEvent.click(screen.getByRole("button", { name: "提交登录" }));

    expect(onLogin).toHaveBeenCalledWith("alice", "password-1");
  });

  it("shows current tenant and logs out", async () => {
    const onLogout = vi.fn().mockResolvedValue(undefined);
    render(<AuthDialog open currentUser={session.user} onLogin={vi.fn()} onRegister={vi.fn()} onLogout={onLogout} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "工作区身份" })).toHaveTextContent("Alice 工作区");
    await userEvent.click(screen.getByRole("button", { name: "退出登录" }));
    expect(onLogout).toHaveBeenCalled();
  });
});
