import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRunJob, compareChapterEvaluations, createNovel, deleteNovel, evaluateChapterVersion, evaluateMemoryQuality, exportNovel as exportNovelFile, getChapterVersionDiff, getMemoryQuality, getNovel, getNovelConflicts, getNovelState, getPlanningVersion, getPlanningVersionDiff, getRunJobEvents, importNovel as importNovelFile, listCreativeBriefVersions, listEvaluationBenchmarks, listModelTraces, listNovels, rebuildMemory, runEvaluationBenchmark, setChapterEvaluationBaseline, startBookRevisionJob, startCandidateGenerationJob, startCanonJob, startNovelJob, updateCreativeBrief } from "./api";
import type { CreateNovelPayload } from "./api";
import { createDefaultCreativeBrief } from "./creativeBrief";
import type { CanonOperation, CreativeBrief, CreativeBriefVersion, EvaluationBenchmarkRun, MemoryQualityHistory, ModelTrace, Novel, PlanningArtifactType, PlanningReviewSubmission, ReviewSubmission, RunJobEventsResponse, StreamEvent, WorkbenchState } from "./types";

const ACTIVE_JOB_STATUSES = new Set(["queued", "running"]);

function pollDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
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

const emptyState = (id: string): WorkbenchState => ({
  novel_id: id,
  status: "idle",
  current_chapter: 1,
  current_phase: "idle",
  chapters_done: 0,
  total_chapters: 0,
  next: [],
  review_node: "",
  planning_review_enabled: false,
  creative_brief: createDefaultCreativeBrief(),
  creative_brief_version: 1,
  creative_brief_review_required: false,
  creative_brief_versions: [],
  world_bible: "",
  characters: [],
  outline: [],
  chapter_plan: {},
  scene_plan: [],
  planning_versions: [],
  chapter_candidates: [],
  current_draft: {},
  issues: [],
  conflicts: [],
  persistence_error: "",
  versions: [],
  evaluations: [],
  run_job: null,
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
  memory: { schema_version: "", chapters: 0, arcs: 0 },
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
});

export function useWorkbench() {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [novel, setNovel] = useState<Novel>();
  const [creativeBriefVersions, setCreativeBriefVersions] = useState<CreativeBriefVersion[]>([]);
  const [modelTraces, setModelTraces] = useState<ModelTrace[]>([]);
  const [evaluationBenchmarks, setEvaluationBenchmarks] = useState<EvaluationBenchmarkRun[]>([]);
  const [memoryQuality, setMemoryQuality] = useState<MemoryQualityHistory>({ latest: null, runs: [] });
  const [state, setState] = useState<WorkbenchState>();
  const [lastNode, setLastNode] = useState<string>();
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [deletingId, setDeletingId] = useState<string>();
  const pollingJobRef = useRef<string | undefined>(undefined);
  const pollingNovelRef = useRef<string | undefined>(undefined);
  const pollAbortRef = useRef<AbortController | undefined>(undefined);
  const selectedIdRef = useRef<string | undefined>(undefined);
  selectedIdRef.current = selectedId;

  const refreshList = useCallback(async () => {
    const items = await listNovels();
    setNovels(items);
    setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id);
  }, []);

  const refreshSelected = useCallback(async (id: string) => {
    const [detail, summary, versions] = await Promise.all([
      getNovel(id),
      getNovelState(id),
      typeof listCreativeBriefVersions === "function"
        ? listCreativeBriefVersions(id)
        : Promise.resolve([] as CreativeBriefVersion[]),
    ]);
    setNovel(detail);
    setState({ ...summary, conflicts: summary.conflicts ?? [] });
    setCreativeBriefVersions(versions);
    if (typeof getNovelConflicts === "function") {
      try {
        const conflicts = await getNovelConflicts(id);
        setState((current) => current?.novel_id === id ? { ...current, conflicts: conflicts?.issues ?? [] } : current);
      } catch {
        // 冲突解释是辅助信息，不应阻塞工作台状态恢复。
      }
    }
  }, []);

  useEffect(() => {
    refreshList().catch((err: unknown) => setError(err instanceof Error ? err.message : "无法加载作品")).finally(() => setIsLoading(false));
  }, [refreshList]);

  useEffect(() => {
    if (pollingNovelRef.current && pollingNovelRef.current !== selectedId) {
      pollAbortRef.current?.abort();
      pollingJobRef.current = undefined;
      pollingNovelRef.current = undefined;
      setIsStreaming(false);
    }
    if (!selectedId) {
      setNovel(undefined);
      setState(undefined);
      setCreativeBriefVersions([]);
      setModelTraces([]);
      setMemoryQuality({ latest: null, runs: [] });
      return;
    }
    setError("");
    setLastNode(undefined);
    refreshSelected(selectedId).catch((err: unknown) => setError(err instanceof Error ? err.message : "无法加载作品状态"));
  }, [refreshSelected, selectedId]);

  const loadModelTraces = useCallback(async (agent = "") => {
    if (!selectedId) return [];
    const traces = await listModelTraces(selectedId, 100, agent);
    setModelTraces(traces);
    return traces;
  }, [selectedId]);

  const loadEvaluationBenchmarks = useCallback(async () => {
    const runs = await listEvaluationBenchmarks();
    setEvaluationBenchmarks(runs);
    return runs;
  }, []);

  const runBenchmark = useCallback(async (includeJudge: boolean, baselineRunId = "") => {
    const run = await runEvaluationBenchmark(includeJudge, baselineRunId);
    setEvaluationBenchmarks((current) => [run, ...current.filter((item) => item.id !== run.id)]);
    return run;
  }, []);

  const loadMemoryQuality = useCallback(async (id = selectedId) => {
    if (!id) return { latest: null, runs: [] } as MemoryQualityHistory;
    const history = await getMemoryQuality(id);
    if (selectedIdRef.current === id) setMemoryQuality(history);
    return history;
  }, [selectedId]);

  const runMemoryQuality = useCallback(async (k = 5) => {
    if (!selectedId) throw new Error("尚未选择作品");
    const run = await evaluateMemoryQuality(selectedId, k);
    await loadMemoryQuality(selectedId);
    return run;
  }, [loadMemoryQuality, selectedId]);

  const rebuildMemoryIndex = useCallback(async (evaluate = true, k = 5) => {
    if (!selectedId) throw new Error("尚未选择作品");
    const result = await rebuildMemory(selectedId, evaluate, k);
    await loadMemoryQuality(selectedId);
    return result;
  }, [loadMemoryQuality, selectedId]);

  const exportNovel = useCallback(async (
    format: string,
    password = "",
    metadata: { author?: string; publisher?: string; language?: string } = {},
  ) => {
    if (!selectedId) throw new Error("尚未选择作品");
    return exportNovelFile(selectedId, format, password, metadata);
  }, [selectedId]);

  const importNovel = useCallback(async (file: File, title = "", password = "") => {
    const result = await importNovelFile(file, title, password);
    await refreshList();
    setSelectedId(result.novel.id);
    return result;
  }, [refreshList]);

  const handleEvent = useCallback((event: StreamEvent) => {
    if (event.type === "node_done") setLastNode(event.node);
    if (event.type === "interrupt") {
      if (event.node === "blueprint_review") {
        setState((current) => current ? {
          ...current,
          status: "blueprint_review",
          review_node: event.node,
          world_bible: event.world_bible,
          characters: event.characters,
          outline: event.outline,
        } : current);
        return;
      }
      if (event.node === "scene_review") {
        setState((current) => current ? {
          ...current,
          status: "scene_review",
          review_node: event.node,
          chapter_plan: event.chapter_plan ?? current.chapter_plan ?? {},
          scene_plan: event.scene_plan,
        } : current);
        return;
      }
      setState((current) => current ? {
        ...current,
        status: "human_review",
        current_draft: {
          ...current.current_draft,
          chapter_number: event.chapter_number,
          title: event.title,
          content: event.content,
          scene_plan: event.scene_plan ?? current.current_draft.scene_plan,
        },
        issues: event.issues ?? current.issues,
        persistence_error: event.persistence_error ?? current.persistence_error,
      } : current);
    }
    if (event.type === "error") setError(event.message);
    if (event.type === "end") {
      setState((current) => current ? {
        ...current,
        chapters_done: event.chapters_done,
        current_chapter: event.current_chapter ?? current.current_chapter,
      } : current);
    }
  }, []);

  const pollRunJob = useCallback(async (id: string, jobId: string) => {
    if (pollingJobRef.current === jobId) return;
    pollAbortRef.current?.abort();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    pollingJobRef.current = jobId;
    pollingNovelRef.current = id;
    setIsStreaming(true);
    let sequence = 0;
    let consecutiveFailures = 0;
    try {
      while (!controller.signal.aborted) {
        let result: RunJobEventsResponse;
        try {
          result = await getRunJobEvents(jobId, sequence, controller.signal);
          consecutiveFailures = 0;
        } catch (reason) {
          if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
          consecutiveFailures += 1;
          if (consecutiveFailures > 5) throw reason;
          await pollDelay(Math.min(350 * (2 ** (consecutiveFailures - 1)), 3000), controller.signal);
          continue;
        }
        for (const record of result.events) {
          sequence = Math.max(sequence, record.sequence);
          handleEvent(record.payload);
        }
        setState((current) => current?.novel_id === id ? {
          ...current,
          status: ACTIVE_JOB_STATUSES.has(result.job.status) ? "running" : current.status,
          run_job: result.job,
        } : current);
        if (result.events.length >= 200) continue;
        if (!ACTIVE_JOB_STATUSES.has(result.job.status)) {
          if (result.job.status === "failed") setError(result.job.error || "后台任务执行失败");
          break;
        }
        await pollDelay(350, controller.signal);
      }
      if (!controller.signal.aborted) {
        if (selectedIdRef.current === id) await refreshSelected(id);
        await refreshList();
      }
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason.message : "后台任务状态读取失败");
        if (selectedIdRef.current === id) await refreshSelected(id).catch(() => undefined);
      }
    } finally {
      if (pollingJobRef.current === jobId) {
        pollingJobRef.current = undefined;
        pollingNovelRef.current = undefined;
        if (selectedIdRef.current === id) setIsStreaming(false);
      }
    }
  }, [handleEvent, refreshList, refreshSelected]);

  useEffect(() => {
    const job = state?.run_job;
    if (selectedId && job && ACTIVE_JOB_STATUSES.has(job.status)) {
      void pollRunJob(selectedId, job.id);
    }
  }, [pollRunJob, selectedId, state?.run_job]);

  const run = useCallback(async (id = selectedId) => {
    if (!id) return;
    setError("");
    try {
      const job = await startNovelJob(id, "run");
      setState((current) => ({
        ...(current ?? emptyState(id)),
        status: "running",
        run_job: job,
      }));
      void pollRunJob(id, job.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "创作运行失败");
      await refreshSelected(id).catch(() => undefined);
    }
  }, [pollRunJob, refreshSelected, selectedId]);

  const resume = useCallback(async (review: ReviewSubmission | PlanningReviewSubmission) => {
    if (!selectedId) return;
    setError("");
    try {
      const job = await startNovelJob(selectedId, "resume", review);
      setState((current) => current ? { ...current, status: "running", run_job: job } : current);
      void pollRunJob(selectedId, job.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "恢复创作失败");
      await refreshSelected(selectedId).catch(() => undefined);
    }
  }, [pollRunJob, refreshSelected, selectedId]);

  const cancelJob = useCallback(async () => {
    const job = state?.run_job;
    if (!job || !ACTIVE_JOB_STATUSES.has(job.status)) return;
    setError("");
    try {
      const cancelled = await cancelRunJob(job.id);
      setState((current) => current ? { ...current, run_job: cancelled } : current);
      if (selectedId) await refreshSelected(selectedId);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "停止后台任务失败");
    }
  }, [refreshSelected, selectedId, state?.run_job]);

  const startBookRevision = useCallback(async (chapterNumber: number, feedback: string) => {
    if (!selectedId) return;
    setError("");
    try {
      const job = await startBookRevisionJob(selectedId, chapterNumber, feedback);
      setState((current) => current ? { ...current, status: "running", run_job: job } : current);
      void pollRunJob(selectedId, job.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "启动全书返修失败");
      await refreshSelected(selectedId).catch(() => undefined);
      throw err;
    }
  }, [pollRunJob, refreshSelected, selectedId]);

  const generateCandidates = useCallback(async (count: number, instruction: string) => {
    if (!selectedId) return;
    setError("");
    try {
      const job = await startCandidateGenerationJob(selectedId, count, instruction);
      setState((current) => current ? { ...current, status: "running", run_job: job } : current);
      void pollRunJob(selectedId, job.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "候选稿生成失败");
      await refreshSelected(selectedId).catch(() => undefined);
      throw err;
    }
  }, [pollRunJob, refreshSelected, selectedId]);

  const compareVersions = useCallback(async (fromVersion: number, toVersion: number) => {
    if (!selectedId || !state) return "";
    const result = await getChapterVersionDiff(
      selectedId,
      state.current_chapter,
      fromVersion,
      toVersion,
    );
    return result.diff;
  }, [selectedId, state]);

  const planningVersionContext = useCallback((): [PlanningArtifactType, number] => {
    if (!state || !["blueprint_review", "scene_review"].includes(state.status)) {
      throw new Error("当前不在规划审阅阶段");
    }
    return state.status === "blueprint_review"
      ? ["blueprint", 0]
      : ["scene", state.current_chapter];
  }, [state]);

  const loadPlanningVersion = useCallback(async (versionNumber: number) => {
    if (!selectedId) throw new Error("尚未选择作品");
    const [artifactType, chapterNumber] = planningVersionContext();
    return getPlanningVersion(selectedId, artifactType, chapterNumber, versionNumber);
  }, [planningVersionContext, selectedId]);

  const comparePlanningVersions = useCallback(async (fromVersion: number, toVersion: number) => {
    if (!selectedId) return "";
    const [artifactType, chapterNumber] = planningVersionContext();
    const result = await getPlanningVersionDiff(
      selectedId,
      artifactType,
      chapterNumber,
      fromVersion,
      toVersion,
    );
    return result.diff;
  }, [planningVersionContext, selectedId]);

  const evaluateVersion = useCallback(async (versionNumber: number, includeJudge: boolean) => {
    if (!selectedId || !state) throw new Error("尚未选择章节");
    const evaluation = await evaluateChapterVersion(selectedId, state.current_chapter, versionNumber, includeJudge);
    setState((current) => current ? { ...current, evaluations: [evaluation, ...current.evaluations] } : current);
    return evaluation;
  }, [selectedId, state]);

  const setEvaluationBaseline = useCallback(async (evaluationId: number) => {
    if (!selectedId || !state) throw new Error("尚未选择章节");
    const evaluation = await setChapterEvaluationBaseline(selectedId, state.current_chapter, evaluationId);
    setState((current) => current ? {
      ...current,
      evaluations: current.evaluations.map((item) => ({ ...item, is_baseline: item.id === evaluation.id })),
    } : current);
    return evaluation;
  }, [selectedId, state]);

  const compareEvaluations = useCallback(async (fromVersion: number, toVersion: number) => {
    if (!selectedId || !state) throw new Error("尚未选择章节");
    return compareChapterEvaluations(selectedId, state.current_chapter, fromVersion, toVersion);
  }, [selectedId, state]);

  const updateCanon = useCallback(async (operation: CanonOperation) => {
    if (!selectedId) return;
    setError("");
    try {
      const job = await startCanonJob(selectedId, operation);
      setState((current) => current ? { ...current, status: "running", run_job: job } : current);
      void pollRunJob(selectedId, job.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Canon 更新失败");
      await refreshSelected(selectedId).catch(() => undefined);
      throw err;
    }
  }, [pollRunJob, refreshSelected, selectedId]);

  const updateBrief = useCallback(async (
    brief: CreativeBrief,
    changeSummary: string,
  ) => {
    if (!selectedId) throw new Error("尚未选择作品");
    setError("");
    try {
      const result = await updateCreativeBrief(
        selectedId,
        brief,
        novel?.creative_brief_version,
        changeSummary,
      );
      setNovel(result);
      if (typeof listCreativeBriefVersions === "function") {
        setCreativeBriefVersions(await listCreativeBriefVersions(selectedId));
      }
      if (result.requires_revalidation) {
        const job = await startNovelJob(selectedId, "resume", { feedback: "recheck" });
        setState((current) => current ? {
          ...current,
          status: "running",
          run_job: job,
          creative_brief: result.creative_brief,
          creative_brief_version: result.creative_brief_version,
          creative_brief_review_required: true,
        } : current);
        void pollRunJob(selectedId, job.id);
      } else {
        await refreshSelected(selectedId);
      }
      return result;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存创作约束失败");
      await refreshSelected(selectedId).catch(() => undefined);
      throw err;
    }
  }, [novel?.creative_brief_version, pollRunJob, refreshSelected, selectedId]);

  const addNovel = useCallback(async (payload: CreateNovelPayload) => {
    setError("");
    const created = await createNovel(payload);
    setNovels((current) => [created, ...current]);
    setSelectedId(created.id);
    setNovel(created);
    setState(emptyState(created.id));
    await run(created.id);
  }, [run]);

  const removeNovel = useCallback(async (id: string) => {
    setError("");
    setDeletingId(id);
    try {
      await deleteNovel(id);
      if (selectedId === id) {
        setNovel(undefined);
        setState(undefined);
        setLastNode(undefined);
      }
      await refreshList();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "删除作品失败");
      throw err;
    } finally {
      setDeletingId(undefined);
    }
  }, [refreshList, selectedId]);

  return { novels, novel, state, creativeBriefVersions, modelTraces, evaluationBenchmarks, memoryQuality, selectedId, setSelectedId, lastNode, error, isLoading, isStreaming, deletingId, run, resume, cancelJob, startBookRevision, generateCandidates, updateCanon, updateBrief, loadModelTraces, loadEvaluationBenchmarks, runBenchmark, loadMemoryQuality, runMemoryQuality, rebuildMemoryIndex, exportNovel, importNovel, compareVersions, loadPlanningVersion, comparePlanningVersions, evaluateVersion, setEvaluationBaseline, compareEvaluations, addNovel, removeNovel };
}
