import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceNav } from "./WorkspaceNav";

afterEach(cleanup);

describe("WorkspaceNav", () => {
  it("exposes stable views and highlights pending planning review", async () => {
    const onChange = vi.fn();
    render(<WorkspaceNav active="write" status="blueprint_review" issueCount={2} onChange={onChange} />);

    expect(screen.getByRole("tab", { name: "写作" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /规划.*待审/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /质量.*2/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "设定" }));
    expect(onChange).toHaveBeenCalledWith("knowledge");
  });
});
