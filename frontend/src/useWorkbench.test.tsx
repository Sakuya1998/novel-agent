import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Novel, RunJob, WorkbenchState } from "./types";

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

const novel: Novel = {
  id: "novel-1",
  title: "雾中剑",
  genre: "武侠",
  inspiration: "失忆剑客",
  style: "gu_long",
  total_chapters: 1,
  chapters: [],
};

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

function state(status: WorkbenchState["status"], runJob: RunJob | null): WorkbenchState {
  return {
    novel_id: novel.id,
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
});
