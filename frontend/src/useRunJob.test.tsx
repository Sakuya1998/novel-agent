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
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
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

  it("ignores an older create response after a newer start for the same novel", async () => {
    const first = deferred<RunJob>();
    const second = deferred<RunJob>();
    const options = createOptions();
    const newerJob = { ...runningJob, id: "job-2" };
    vi.mocked(getRunJobEvents).mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useRunJob(options));
    const firstStart = result.current.startJob("novel-1", () => first.promise);
    const secondStart = result.current.startJob("novel-1", () => second.promise);

    await act(async () => { second.resolve(newerJob); await secondStart; });
    await act(async () => { first.resolve(runningJob); await firstStart; });

    expect(options.onJobUpdate).toHaveBeenCalledExactlyOnceWith("novel-1", newerJob);
    expect(getRunJobEvents).toHaveBeenCalledExactlyOnceWith("job-2", 0, expect.any(AbortSignal));
    expect(vi.mocked(getRunJobEvents).mock.calls[0][2]?.aborted).toBe(false);
  });

  it("does not apply a pending create response after unmount", async () => {
    const pending = deferred<RunJob>();
    const options = createOptions();
    vi.mocked(getRunJobEvents).mockResolvedValue(response(completedJob, 1));
    const { result, unmount } = renderHook(() => useRunJob(options));
    const start = result.current.startJob("novel-1", () => pending.promise);
    unmount();
    await act(async () => { pending.resolve(runningJob); await start; });

    expect(getRunJobEvents).not.toHaveBeenCalled();
    expect(options.onJobUpdate).not.toHaveBeenCalled();
    expect(options.onEvent).not.toHaveBeenCalled();
    expect(options.onSettled).not.toHaveBeenCalled();
  });

  it("invalidates a pending start even after switching back to its novel", async () => {
    const pending = deferred<RunJob>();
    const options = createOptions();
    vi.mocked(getRunJobEvents).mockResolvedValue(response(completedJob));
    const { result, rerender } = renderHook(
      ({ selectedId }) => useRunJob({ ...options, selectedId }),
      { initialProps: { selectedId: "novel-1" } },
    );
    const start = result.current.startJob("novel-1", () => pending.promise);
    rerender({ selectedId: "novel-2" });
    rerender({ selectedId: "novel-1" });
    await act(async () => { pending.resolve(runningJob); await start; });

    expect(getRunJobEvents).not.toHaveBeenCalled();
    expect(options.onJobUpdate).not.toHaveBeenCalled();
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

  it("keeps polling when cancellation is only requested on an active job", async () => {
    const pendingPoll = deferred<RunJobEventsResponse>();
    const cancellationRequested = { ...runningJob, cancel_requested: true };
    const cancelledJob = { ...cancellationRequested, status: "cancelled" as const };
    const options = createOptions({ activeJob: runningJob });
    vi.mocked(getRunJobEvents).mockReturnValue(pendingPoll.promise);
    vi.mocked(cancelRunJob).mockResolvedValue(cancellationRequested);

    const { result } = renderHook(() => useRunJob(options));
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalled());
    const pollingSignal = vi.mocked(getRunJobEvents).mock.calls[0][2]!;

    await act(() => result.current.cancelJob());

    expect(pollingSignal.aborted).toBe(false);
    expect(options.onJobUpdate).toHaveBeenCalledWith("novel-1", cancellationRequested);
    expect(options.onSettled).not.toHaveBeenCalled();
    expect(result.current.connectionStatus).toBe("polling");

    pendingPoll.resolve(response(cancelledJob));
    await waitFor(() => expect(result.current.connectionStatus).toBe("idle"));
    expect(options.onSettled).toHaveBeenCalledTimes(1);
  });

  it("ignores a delayed cancellation response after another job replaces it", async () => {
    const firstPoll = deferred<RunJobEventsResponse>();
    const secondPoll = deferred<RunJobEventsResponse>();
    const pendingCancellation = deferred<RunJob>();
    const replacementJob = { ...runningJob, id: "job-2" };
    const cancelledJob = { ...runningJob, status: "cancelled" as const };
    const options = createOptions({ activeJob: runningJob });
    vi.mocked(getRunJobEvents)
      .mockReturnValueOnce(firstPoll.promise)
      .mockReturnValueOnce(secondPoll.promise);
    vi.mocked(cancelRunJob).mockReturnValue(pendingCancellation.promise);

    const { result } = renderHook(() => useRunJob(options));
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalledTimes(1));
    const cancellation = result.current.cancelJob();

    await act(() => result.current.startJob("novel-1", async () => replacementJob));
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalledTimes(2));
    const replacementSignal = vi.mocked(getRunJobEvents).mock.calls[1][2]!;

    pendingCancellation.resolve(cancelledJob);
    await act(() => cancellation);

    expect(replacementSignal.aborted).toBe(false);
    expect(options.onJobUpdate).not.toHaveBeenCalledWith("novel-1", cancelledJob);
    expect(options.onSettled).not.toHaveBeenCalled();
    expect(result.current.connectionStatus).toBe("polling");

    secondPoll.resolve(response({ ...replacementJob, status: "completed" }));
    await waitFor(() => expect(result.current.connectionStatus).toBe("idle"));
  });

  it("ignores a delayed cancellation failure after another job replaces it", async () => {
    const firstPoll = deferred<RunJobEventsResponse>();
    const secondPoll = deferred<RunJobEventsResponse>();
    const pendingCancellation = deferred<RunJob>();
    const replacementJob = { ...runningJob, id: "job-2" };
    const options = createOptions({ activeJob: runningJob });
    vi.mocked(getRunJobEvents)
      .mockReturnValueOnce(firstPoll.promise)
      .mockReturnValueOnce(secondPoll.promise);
    vi.mocked(cancelRunJob).mockReturnValue(pendingCancellation.promise);

    const { result } = renderHook(() => useRunJob(options));
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalledTimes(1));
    const cancellation = result.current.cancelJob();

    await act(() => result.current.startJob("novel-1", async () => replacementJob));
    await waitFor(() => expect(getRunJobEvents).toHaveBeenCalledTimes(2));

    pendingCancellation.reject(new Error("stale cancellation failure"));
    await act(() => cancellation);

    expect(options.onError).not.toHaveBeenCalled();
    expect(result.current.connectionStatus).toBe("polling");

    secondPoll.resolve(response({ ...replacementJob, status: "completed" }));
    await waitFor(() => expect(result.current.connectionStatus).toBe("idle"));
  });
});
