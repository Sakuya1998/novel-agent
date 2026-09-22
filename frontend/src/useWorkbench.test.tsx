import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Novel, RunJob, RunJobEventsResponse, WorkbenchState } from "./types";

const api = vi.hoisted(() => ({
  cancelRunJob: vi.fn(),
  compareChapterEvaluations: vi.fn(),
  createNovel: vi.fn(),
  deleteNovel: vi.fn(),
  evaluateChapterVersion: vi.fn(),
  getChapterVersionDiff: vi.fn(),
  getNovel: vi.fn(),
  getNovelState: vi.fn(),
  getRunJobEvents: vi.fn(),
  listCreativeBriefVersions: vi.fn(),
  listModelTraces: vi.fn(),
  listNovels: vi.fn(),
  setChapterEvaluationBaseline: vi.fn(),
  startBookRevisionJob: vi.fn(),
  startCandidateGenerationJob: vi.fn(),
  startCanonJob: vi.fn(),
  startNovelJob: vi.fn(),
}));

vi.mock("./api", () => api);

import { useWorkbench } from "./useWorkbench";
import { useReviewWorkflow } from "./useReviewWorkflow";

const novel: Novel = {
  id: "novel-1",
  title: "雾中剑",
  genre: "武侠",
  inspiration: "失忆剑客",
  style: "gu_long",
  total_chapters: 1,
  chapters: [],
};

const secondNovel: Novel = {
  ...novel,
  id: "novel-2",
  title: "长夜灯塔",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function job(status: RunJob["status"]): RunJob {
  return {
    id: "job-1",
    novel_id: novel.id,
    action: "run",
    status,
    request: {},
    current_node: status === "running" ? "scene_writer" : "human_review",
    error: "",
    cancel_requested: false,
    created_at: "2026-08-17",
    updated_at: "2026-08-17",
  };
}

function state(status: WorkbenchState["status"], runJob: RunJob | null, novelId = novel.id): WorkbenchState {
  return {
    novel_id: novelId,
    status,
    current_chapter: 1,
    current_phase: "writing",
    chapters_done: 0,
    total_chapters: 1,
    next: [],
    current_draft: {},
    issues: [],
    persistence_error: "",
    versions: [],
    evaluations: [],
    chapter_candidates: [],
    run_job: runJob,
  model_usage: {
      attempts: 0,
      successful_calls: 0,
      failed_attempts: 0,
      fallback_attempts: 0,
      duration_ms: 0,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      estimated_attempts: 0,
    by_agent: [],
  },
  memory: { schema_version: "book-memory-v1", chapters: 1, arcs: 1 },
  canon: {
      version: 0,
      world_facts: 0,
      characters: 0,
      timeline_entries: 0,
      confirmed_facts: 0,
      deprecated_facts: 0,
      aliases: 0,
      audit_entries: 0,
      narrative_threads: 0,
      open_threads: 0,
      resolved_threads: 0,
      overdue_threads: 0,
    },
  };
}

describe("useWorkbench background jobs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listNovels.mockResolvedValue([novel]);
    api.listCreativeBriefVersions.mockResolvedValue([]);
    api.listModelTraces.mockResolvedValue([]);
    api.getNovel.mockResolvedValue(novel);
  });

  it("exposes persisted job connection recovery controls", async () => {
    api.getNovelState.mockResolvedValue(state("idle", null));

    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state?.status).toBe("idle"));
    expect(result.current.connectionStatus).toBe("idle");
    expect(result.current.retryRunConnection).toEqual(expect.any(Function));
  });

  it.each(["revision", "candidate", "restore"])("preserves review input when the real %s command cannot start", async (command) => {
    api.getNovelState.mockResolvedValue(state("human_review", null));
    api.startNovelJob.mockRejectedValue(new Error("start unavailable"));
    const { result } = renderHook(() => {
      const workbench = useWorkbench();
      const review = useReviewWorkflow({ novelId: workbench.selectedId ?? "", chapterNumber: 1, onSubmit: workbench.resume });
      return { workbench, review };
    });
    await waitFor(() => expect(result.current.workbench.state?.status).toBe("human_review"));
    act(() => {
      result.current.review.selectScene(2);
      result.current.review.setFeedback("Keep my revision notes");
    });

    await act(async () => {
      if (command === "revision") await result.current.review.submitRevision();
      else await expect(result.current.review.replaceDraft(command === "candidate"
        ? { feedback: "candidate", candidate_id: "c1" }
        : { feedback: "restore", version_number: 1 })).rejects.toThrow("start unavailable");
    });

    expect(result.current.workbench.error).toBe("start unavailable");
    expect(result.current.review.error).toBe("start unavailable");
    expect(result.current.review.feedback).toBe("Keep my revision notes");
    expect(result.current.review.sceneNumber).toBe(2);
    expect(result.current.review.busyAction).toBe("");
    expect(result.current.review.focusRequest).toBe(0);
  });

  it("reconnects to an active persisted job after loading the project", async () => {
    api.getNovelState
      .mockResolvedValueOnce(state("running", job("running")))
      .mockResolvedValue(state("human_review", job("waiting_review")));
    api.getRunJobEvents.mockResolvedValue({
      job: job("waiting_review"),
      events: [
        {
          id: 1,
          job_id: "job-1",
          sequence: 1,
          event_type: "node_done",
          payload: { type: "node_done", node: "consistency_checker" },
          created_at: "2026-08-17",
        },
        {
          id: 2,
          job_id: "job-1",
          sequence: 2,
          event_type: "interrupt",
          payload: { type: "interrupt", node: "human_review", chapter_number: 1, title: "雾起" },
          created_at: "2026-08-17",
        },
      ],
    });

    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state?.status).toBe("human_review"));
    expect(api.getRunJobEvents).toHaveBeenCalledWith("job-1", 0, expect.any(AbortSignal));
    expect(result.current.lastNode).toBe("consistency_checker");
    expect(result.current.isStreaming).toBe(false);
  });

  it("starts and reconnects to a candidate generation job", async () => {
    const queued = { ...job("queued"), action: "candidate_generation" };
    const completed = { ...job("completed"), action: "candidate_generation" };
    api.getNovelState.mockResolvedValue(state("human_review", job("waiting_review")));
    api.startCandidateGenerationJob.mockResolvedValue(queued);
    api.getRunJobEvents.mockResolvedValue({
      job: completed,
      events: [{
        id: 1,
        job_id: completed.id,
        sequence: 1,
        event_type: "candidates_ready",
        payload: { type: "candidates_ready", chapter_number: 1, count: 3 },
        created_at: "2026-08-17",
      }],
    });

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state?.status).toBe("human_review"));
    await act(async () => {
      await result.current.generateCandidates(3, "强化人物冲突");
    });

    expect(api.startCandidateGenerationJob).toHaveBeenCalledWith(
      novel.id,
      3,
      "强化人物冲突",
    );
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
  });

  it("ignores a stale project response after the user selects another novel", async () => {
    const firstDetail = deferred<Novel>();
    const firstState = deferred<WorkbenchState>();
    api.listNovels.mockResolvedValue([novel, secondNovel]);
    api.getNovel.mockImplementation((id: string) => id === novel.id ? firstDetail.promise : Promise.resolve(secondNovel));
    api.getNovelState.mockImplementation((id: string) => id === novel.id
      ? firstState.promise
      : Promise.resolve(state("idle", null, secondNovel.id)));

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(api.getNovel).toHaveBeenCalledWith(novel.id));

    act(() => result.current.setSelectedId(secondNovel.id));
    await waitFor(() => expect(result.current.novel?.id).toBe(secondNovel.id));

    await act(async () => {
      firstDetail.resolve(novel);
      firstState.resolve(state("human_review", null));
      await Promise.resolve();
    });

    expect(result.current.novel?.id).toBe(secondNovel.id);
    expect(result.current.state?.novel_id).toBe(secondNovel.id);
  });

  it("ignores late polling events from a previously selected novel", async () => {
    const stalePoll = deferred<RunJobEventsResponse>();
    api.listNovels.mockResolvedValue([novel, secondNovel]);
    api.getNovel.mockImplementation((id: string) => Promise.resolve(id === novel.id ? novel : secondNovel));
    api.getNovelState.mockImplementation((id: string) => Promise.resolve(
      id === novel.id
        ? state("running", job("running"))
        : state("idle", null, secondNovel.id),
    ));
    api.getRunJobEvents.mockReturnValue(stalePoll.promise);

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(api.getRunJobEvents).toHaveBeenCalled());

    act(() => result.current.setSelectedId(secondNovel.id));
    await waitFor(() => expect(result.current.state?.novel_id).toBe(secondNovel.id));

    await act(async () => {
      stalePoll.resolve({
        job: job("waiting_review"),
        events: [{
          id: 1,
          job_id: "job-1",
          sequence: 1,
          event_type: "interrupt",
          payload: {
            type: "interrupt",
            node: "human_review",
            chapter_number: 1,
            title: "旧作品污染",
          },
          created_at: "2026-08-17",
        }],
      });
      await Promise.resolve();
    });

    expect(result.current.state?.novel_id).toBe(secondNovel.id);
    expect(result.current.state?.current_draft.title).not.toBe("旧作品污染");
  });
});
