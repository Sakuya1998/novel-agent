import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
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
});
