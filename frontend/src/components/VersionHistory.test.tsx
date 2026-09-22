import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VersionHistory } from "./VersionHistory";

afterEach(cleanup);

describe("VersionHistory", () => {
  it("compares the latest versions and restores a selected snapshot", async () => {
    const onCompare = vi.fn().mockResolvedValue("-旧句\n+新句");
    const onRestore = vi.fn().mockResolvedValue(undefined);
    render(<VersionHistory
      versions={[
        { id: 1, chapter_number: 1, version_number: 1, source: "initial", word_count: 100, preview: "旧", created_at: "2026-08-17" },
        { id: 2, chapter_number: 1, version_number: 2, source: "scene_revision", word_count: 108, preview: "新", created_at: "2026-08-17" },
      ]}
      disabled={false}
      onCompare={onCompare}
      onRestore={onRestore}
    />);

    await userEvent.click(screen.getByRole("button", { name: "比较版本" }));
    expect(onCompare).toHaveBeenCalledWith(1, 2);
    expect(await screen.findByText(/新句/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "恢复 v1" }));
    expect(onRestore).toHaveBeenCalledWith(1);
  });

  it("notifies after restoration resolves", async () => {
    let resolve!: () => void;
    const onRestore = vi.fn(() => new Promise<void>((done) => { resolve = done; }));
    const onRestored = vi.fn();
    render(<VersionHistory versions={[{ id: 1, chapter_number: 1, version_number: 1, source: "initial", word_count: 100, preview: "旧", created_at: "2026-08-17" }]} disabled={false} onCompare={vi.fn().mockResolvedValue("")} onRestore={onRestore} onRestored={onRestored} />);

    const click = userEvent.click(screen.getByRole("button", { name: "恢复 v1" }));
    await waitFor(() => expect(onRestore).toHaveBeenCalledOnce());
    expect(onRestored).not.toHaveBeenCalled();
    resolve();
    await click;
    expect(onRestored).toHaveBeenCalledOnce();
  });

  it("reports a rejected restoration without notifying completion", async () => {
    const failure = new Error("version unavailable");
    const onRestore = vi.fn().mockRejectedValue(failure);
    const onRestored = vi.fn();
    const onError = vi.fn();
    render(<VersionHistory versions={[{ id: 1, chapter_number: 1, version_number: 1, source: "initial", word_count: 100, preview: "旧", created_at: "2026-08-17" }]} disabled={false} onCompare={vi.fn().mockResolvedValue("")} onRestore={onRestore} onRestored={onRestored} onError={onError} />);

    await userEvent.click(screen.getByRole("button", { name: "恢复 v1" }));

    expect(onRestored).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(failure);
  });
});
