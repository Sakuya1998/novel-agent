import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getReadiness } from "./api";
import { useServiceStatus } from "./useServiceStatus";

vi.mock("./api", () => ({ getReadiness: vi.fn() }));

afterEach(() => {
  vi.mocked(getReadiness).mockReset();
});

describe("useServiceStatus", () => {
  it("reports ready and degraded backend states", async () => {
    vi.mocked(getReadiness).mockResolvedValue({ status: "ready", checks: {} });
    const ready = renderHook(() => useServiceStatus(60_000));
    await waitFor(() => expect(ready.result.current).toBe("ready"));
    ready.unmount();

    vi.mocked(getReadiness).mockResolvedValue({ status: "not_ready", checks: {} });
    const degraded = renderHook(() => useServiceStatus(60_000));
    await waitFor(() => expect(degraded.result.current).toBe("degraded"));
    degraded.unmount();
  });

  it("reports an unreachable backend", async () => {
    vi.mocked(getReadiness).mockRejectedValue(new Error("offline"));
    const result = renderHook(() => useServiceStatus(60_000));
    await waitFor(() => expect(result.result.current).toBe("offline"));
    result.unmount();
  });
});
