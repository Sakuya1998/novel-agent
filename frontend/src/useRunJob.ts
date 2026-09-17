import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRunJob, getRunJobEvents } from "./api";
import type { RunJob, RunJobEventsResponse, StreamEvent } from "./types";

export type RunConnectionStatus = "idle" | "polling" | "reconnecting" | "failed";

export interface UseRunJobOptions {
  selectedId?: string;
  activeJob?: RunJob | null;
  onEvent: (novelId: string, event: StreamEvent) => void;
  onJobUpdate: (novelId: string, job: RunJob) => void;
  onSettled: (novelId: string) => Promise<void>;
  onError: (novelId: string, message: string) => void;
}

const ACTIVE_JOB_STATUSES = new Set(["queued", "running"]);
const RETRY_DELAYS = [350, 700, 1400, 2800, 3000];

interface ActiveRun {
  novelId: string;
  jobId: string;
}

function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function pollDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      window.clearTimeout(timeout);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timeout = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function useRunJob(options: UseRunJobOptions) {
  const [connectionStatus, setConnectionStatus] = useState<RunConnectionStatus>("idle");
  const optionsRef = useRef(options);
  const activeRunRef = useRef<ActiveRun | undefined>(undefined);
  const currentJobRef = useRef<RunJob | null>(null);
  const sequenceRef = useRef(0);
  const abortRef = useRef<AbortController | undefined>(undefined);
  optionsRef.current = options;

  const isActiveRun = useCallback((run: ActiveRun) => {
    const current = activeRunRef.current;
    return optionsRef.current.selectedId === run.novelId
      && current?.novelId === run.novelId
      && current.jobId === run.jobId;
  }, []);

  const isCurrent = useCallback((run: ActiveRun, controller: AbortController) => {
    return !controller.signal.aborted && isActiveRun(run);
  }, [isActiveRun]);

  const poll = useCallback(async (run: ActiveRun) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    activeRunRef.current = run;
    setConnectionStatus("polling");
    let failureCount = 0;
    let settled = false;

    try {
      while (!controller.signal.aborted) {
        let result: RunJobEventsResponse;
        try {
          result = await getRunJobEvents(run.jobId, sequenceRef.current, controller.signal);
          failureCount = 0;
        } catch (reason) {
          if (isAbortError(reason)) throw reason;
          if (!isCurrent(run, controller)) return;
          if (failureCount === RETRY_DELAYS.length) throw reason;
          setConnectionStatus("reconnecting");
          await pollDelay(RETRY_DELAYS[failureCount], controller.signal);
          failureCount += 1;
          if (isCurrent(run, controller)) setConnectionStatus("polling");
          continue;
        }

        if (!isCurrent(run, controller)
          || result.job.id !== run.jobId
          || result.job.novel_id !== run.novelId) return;

        currentJobRef.current = result.job;
        for (const record of result.events) {
          if (!isCurrent(run, controller)) return;
          if (record.job_id !== run.jobId) continue;
          optionsRef.current.onEvent(run.novelId, record.payload);
          sequenceRef.current = Math.max(sequenceRef.current, record.sequence);
        }
        if (!isCurrent(run, controller)) return;
        optionsRef.current.onJobUpdate(run.novelId, result.job);

        if (result.events.length >= 200) continue;
        if (!ACTIVE_JOB_STATUSES.has(result.job.status)) {
          if (result.job.status === "failed") {
            optionsRef.current.onError(run.novelId, result.job.error || "后台任务执行失败");
          }
          settled = true;
          break;
        }
        await pollDelay(350, controller.signal);
      }

      if (settled && isCurrent(run, controller)) {
        setConnectionStatus("idle");
        await optionsRef.current.onSettled(run.novelId);
      }
    } catch (reason) {
      if (!isAbortError(reason) && isCurrent(run, controller)) {
        setConnectionStatus("failed");
        optionsRef.current.onError(
          run.novelId,
          reason instanceof Error ? reason.message : "后台任务状态读取失败",
        );
        if (!settled) await optionsRef.current.onSettled(run.novelId).catch(() => undefined);
      }
    }
  }, [isCurrent]);

  const beginPolling = useCallback((novelId: string, job: RunJob, resetSequence: boolean) => {
    const current = activeRunRef.current;
    if (current?.novelId === novelId && current.jobId === job.id && abortRef.current && !abortRef.current.signal.aborted) {
      return;
    }
    if (resetSequence) sequenceRef.current = 0;
    currentJobRef.current = job;
    void poll({ novelId, jobId: job.id });
  }, [poll]);

  const startJob = useCallback(async (novelId: string, createJob: () => Promise<RunJob>) => {
    const job = await createJob();
    if (optionsRef.current.selectedId !== novelId || job.novel_id !== novelId) return;
    optionsRef.current.onJobUpdate(novelId, job);
    beginPolling(novelId, job, true);
  }, [beginPolling]);

  const cancelJob = useCallback(async () => {
    const run = activeRunRef.current;
    const job = currentJobRef.current;
    if (!run || !job || !ACTIVE_JOB_STATUSES.has(job.status)) return;
    try {
      const cancelled = await cancelRunJob(run.jobId);
      if (!isActiveRun(run)
        || cancelled.id !== run.jobId
        || cancelled.novel_id !== run.novelId) return;
      currentJobRef.current = cancelled;
      optionsRef.current.onJobUpdate(run.novelId, cancelled);
      if (ACTIVE_JOB_STATUSES.has(cancelled.status)) return;
      abortRef.current?.abort();
      setConnectionStatus("idle");
      await optionsRef.current.onSettled(run.novelId);
    } catch (reason) {
      if (isActiveRun(run)) {
        optionsRef.current.onError(
          run.novelId,
          reason instanceof Error ? reason.message : "停止后台任务失败",
        );
      }
    }
  }, [isActiveRun]);

  const retry = useCallback(() => {
    const run = activeRunRef.current;
    const job = currentJobRef.current;
    if (connectionStatus !== "failed" || !run || !job || optionsRef.current.selectedId !== run.novelId) return;
    void poll(run);
  }, [connectionStatus, poll]);

  useEffect(() => {
    const current = activeRunRef.current;
    if (current && current.novelId !== options.selectedId) {
      abortRef.current?.abort();
      abortRef.current = undefined;
      activeRunRef.current = undefined;
      currentJobRef.current = null;
      sequenceRef.current = 0;
      setConnectionStatus("idle");
    }

    const job = options.activeJob;
    if (options.selectedId && job && job.novel_id === options.selectedId && ACTIVE_JOB_STATUSES.has(job.status)) {
      beginPolling(options.selectedId, job, true);
    }
  }, [beginPolling, options.activeJob?.id, options.activeJob?.status, options.selectedId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    connectionStatus,
    isStreaming: connectionStatus === "polling" || connectionStatus === "reconnecting",
    startJob,
    cancelJob,
    retry,
  };
}
