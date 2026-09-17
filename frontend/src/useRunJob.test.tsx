import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRunJob, getRunJobEvents } from "./api";
import type { RunJob, RunJobEventsResponse, StreamEvent } from "./types";
import { useRunJob, type UseRunJobOptions } from "./useRunJob";

vi.mock("./api", () => ({
  cancelRunJob: vi.fn(),
  getRunJobEvents: vi.fn(),
}));

const runningJob: RunJob = {
  id: "job-1",
  novel_id: "novel-1",
  action: "run",
  status: "running",
  request: {},
  current_node: "scene_writer",
  error: "",
  cancel_requested: false,
  created_at: "2026-09-17",
  updated_at: "2026-09-17",
};

const completedJob: RunJob = {
  ...runningJob,
  status: "completed",
};

const nodeEvent: StreamEvent = { type: "node_done", node: "scene_writer" };

function response(job: RunJob, sequence?: number): RunJobEventsResponse {
  return {
    job,
    events: sequence === undefined ? [] : [{
      id: sequence,
      job_id: job.id,
      sequence,
      event_type: nodeEvent.type,
      payload: nodeEvent,
      created_at: "2026-09-17",
    }],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function createOptions(overrides: Partial<UseRunJobOptions> = {}): UseRunJobOptions {
  return {
    selectedId: "novel-1",
    activeJob: null,
    onEvent: vi.fn(),
    onJobUpdate: vi.fn(),
    onSettled: vi.fn().mockResolvedValue(undefined),
    onError: vi.fn(),
    ...overrides,
  };
}

describe("useRunJob", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reconnects after a transient polling failure without losing the event sequence", async () => {
    const options = createOptions();
    vi.mocked(getRunJobEvents)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(response(runningJob, 4))
      .mockResolvedValueOnce(response(completedJob));

    const { result } = renderHook(() => useRunJob(options));
    await act(() => result.current.startJob("novel-1", async () => runningJob));

    await waitFor(() => expect(result.current.connectionStatus).toBe("idle"));
    expect(getRunJobEvents).toHaveBeenNthCalledWith(2, runningJob.id, 0, expect.any(AbortSignal));
    expect(getRunJobEvents).toHaveBeenNthCalledWith(3, runningJob.id, 4, expect.any(AbortSignal));
    expect(options.onEvent).toHaveBeenCalledWith("novel-1", nodeEvent);
    expect(options.onSettled).toHaveBeenCalledWith("novel-1");
  });

  it("drops events after the selected novel changes", async () => {
    const pendingPoll = deferred<RunJobEventsResponse>();
    const options = createOptions({ activeJob: runningJob });
    vi.mocked(getRunJobEvents).mockReturnValue(pendingPoll.promise);

    const view = renderHook(({ selectedId }) => useRunJob({ ...options, selectedId }), {
      initialProps: { selectedId: "novel-1" as string | undefined },
    });
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalled());

    view.rerender({ selectedId: "novel-2" });
    pendingPoll.resolve(response(completedJob, 1));

    await waitFor(() => expect(view.result.current.connectionStatus).toBe("idle"));
    expect(options.onEvent).not.toHaveBeenCalled();
    expect(options.onJobUpdate).not.toHaveBeenCalled();
    expect(options.onSettled).not.toHaveBeenCalled();
  });

  it("retries the current persisted job from the last acknowledged sequence", async () => {
    vi.useFakeTimers();
    const options = createOptions();
    const createJob = vi.fn().mockResolvedValue(runningJob);
    vi.mocked(getRunJobEvents)
      .mockResolvedValueOnce(response(runningJob, 4))
      .mockRejectedValueOnce(new Error("offline-1"))
      .mockRejectedValueOnce(new Error("offline-2"))
      .mockRejectedValueOnce(new Error("offline-3"))
      .mockRejectedValueOnce(new Error("offline-4"))
      .mockRejectedValueOnce(new Error("offline-5"))
      .mockRejectedValueOnce(new Error("offline-6"))
      .mockResolvedValueOnce(response(completedJob));

    const { result } = renderHook(() => useRunJob(options));
    await act(() => result.current.startJob("novel-1", createJob));
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(result.current.connectionStatus).toBe("failed");
    expect(getRunJobEvents).toHaveBeenCalledTimes(7);

    await act(() => result.current.retry());
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(createJob).toHaveBeenCalledTimes(1);
    expect(getRunJobEvents).toHaveBeenLastCalledWith(runningJob.id, 4, expect.any(AbortSignal));
    expect(result.current.connectionStatus).toBe("idle");
  });

  it("cancels the current persisted job and settles its novel", async () => {
    const pendingPoll = deferred<RunJobEventsResponse>();
    const cancelledJob = { ...runningJob, status: "cancelled" as const };
    const options = createOptions({ activeJob: runningJob });
    vi.mocked(getRunJobEvents).mockReturnValue(pendingPoll.promise);
    vi.mocked(cancelRunJob).mockResolvedValue(cancelledJob);

    const { result } = renderHook(() => useRunJob(options));
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalled());

    await act(() => result.current.cancelJob());

    expect(cancelRunJob).toHaveBeenCalledWith(runningJob.id);
    expect(options.onJobUpdate).toHaveBeenCalledWith("novel-1", cancelledJob);
    expect(options.onSettled).toHaveBeenCalledWith("novel-1");
    expect(result.current.connectionStatus).toBe("idle");
  });
});
