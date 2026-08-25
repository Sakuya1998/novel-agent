import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { useDialogLifecycle } from "./useDialogLifecycle";

afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
});

function DialogHarness({ busy = false, onClose = vi.fn() }: { busy?: boolean; onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  const close = () => {
    onClose();
    setOpen(false);
  };
  const { dialogRef, onBackdropMouseDown } = useDialogLifecycle<HTMLElement>(open, close, busy);

  return <>
    <button type="button" onClick={() => setOpen(true)}>打开弹窗</button>
    {open ? <div data-testid="backdrop" onMouseDown={onBackdropMouseDown}>
      <section ref={dialogRef} tabIndex={-1} role="dialog" aria-label="测试弹窗">
        <button type="button">弹窗操作</button>
      </section>
    </div> : null}
  </>;
}

describe("useDialogLifecycle", () => {
  it("closes with Escape, restores scrolling, and returns focus", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DialogHarness onClose={onClose} />);

    const trigger = screen.getByRole("button", { name: "打开弹窗" });
    trigger.focus();
    await user.click(trigger);

    await waitFor(() => expect(document.body).toHaveStyle({ overflow: "hidden" }));
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
    expect(trigger).toHaveFocus();
  });

  it("closes only when the backdrop itself is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DialogHarness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "打开弹窗" }));

    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(screen.getByTestId("backdrop"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps a busy dialog open on Escape and backdrop clicks", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DialogHarness busy onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "打开弹窗" }));

    await user.keyboard("{Escape}");
    fireEvent.mouseDown(screen.getByTestId("backdrop"));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
