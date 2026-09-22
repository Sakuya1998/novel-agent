import { useCallback, useEffect, useRef, useState } from "react";
import { compareChapterEvaluations, createNovel, deleteNovel, evaluateChapterVersion, evaluateMemoryQuality, exportNovel as exportNovelFile, getChapterVersionDiff, getMemoryQuality, getNovel, getNovelConflicts, getNovelState, getPlanningVersion, getPlanningVersionDiff, importNovel as importNovelFile, listCreativeBriefVersions, listEvaluationBenchmarks, listModelTraces, listNovels, rebuildMemory, runEvaluationBenchmark, setChapterEvaluationBaseline, startBookRevisionJob, startCandidateGenerationJob, startCanonJob, startNovelJob, updateCreativeBrief } from "./api";
import type { CreateNovelPayload } from "./api";
import { createDefaultCreativeBrief } from "./creativeBrief";
import type { CanonOperation, CreativeBrief, CreativeBriefVersion, EvaluationBenchmarkRun, MemoryQualityHistory, ModelTrace, Novel, PlanningArtifactType, PlanningReviewSubmission, ReviewSubmission, RunJob, StreamEvent, WorkbenchState } from "./types";
import { useRunJob } from "./useRunJob";

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

export function useWorkbench(enabled = true) {
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
  const [deletingId, setDeletingId] = useState<string>();
  const selectedIdRef = useRef<string | undefined>(undefined);
  selectedIdRef.current = selectedId;

  const updateStateFor = useCallback((id: string, update: (current: WorkbenchState) => WorkbenchState) => {
    setState((current) => current?.novel_id === id ? update(current) : current);
  }, []);

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
    if (selectedIdRef.current !== id) return;
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
    if (!enabled) {
      setNovels([]);
      setSelectedId(undefined);
      setNovel(undefined);
      setState(undefined);
      setCreativeBriefVersions([]);
      setModelTraces([]);
      setMemoryQuality({ latest: null, runs: [] });
      setError("");
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    refreshList().catch((err: unknown) => setError(err instanceof Error ? err.message : "无法加载作品")).finally(() => setIsLoading(false));
  }, [enabled, refreshList]);

  useEffect(() => {
    if (!enabled || !selectedId) {
      setNovel(undefined);
      setState(undefined);
      setCreativeBriefVersions([]);
      setModelTraces([]);
      setMemoryQuality({ latest: null, runs: [] });
      return;
    }
    setError("");
    setLastNode(undefined);
    refreshSelected(selectedId).catch((err: unknown) => {
      if (selectedIdRef.current === selectedId) {
        setError(err instanceof Error ? err.message : "无法加载作品状态");
      }
    });
  }, [enabled, refreshSelected, selectedId]);

  const loadModelTraces = useCallback(async (agent = "") => {
    if (!selectedId) return [];
    const id = selectedId;
    const traces = await listModelTraces(id, 100, agent);
    if (selectedIdRef.current === id) setModelTraces(traces);
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

  const handleEvent = useCallback((id: string, event: StreamEvent) => {
    if (event.type === "node_done" && selectedIdRef.current === id) setLastNode(event.node);
    if (event.type === "interrupt") {
      if (event.node === "blueprint_review") {
        updateStateFor(id, (current) => ({
          ...current,
          status: "blueprint_review",
          review_node: event.node,
          world_bible: event.world_bible,
          characters: event.characters,
          outline: event.outline,
        }));
        return;
      }
      if (event.node === "scene_review") {
        updateStateFor(id, (current) => ({
          ...current,
          status: "scene_review",
          review_node: event.node,
          chapter_plan: event.chapter_plan ?? current.chapter_plan ?? {},
          scene_plan: event.scene_plan,
        }));
        return;
      }
      updateStateFor(id, (current) => ({
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
      }));
    }
    if (event.type === "error" && selectedIdRef.current === id) setError(event.message);
    if (event.type === "end") {
      updateStateFor(id, (current) => ({
        ...current,
        chapters_done: event.chapters_done,
        current_chapter: event.current_chapter ?? current.current_chapter,
      }));
    }
  }, [updateStateFor]);

  const handleJobUpdate = useCallback((id: string, job: RunJob) => {
    updateStateFor(id, (current) => ({
      ...current,
      status: job.status === "queued" || job.status === "running" ? "running" : current.status,
      run_job: job,
    }));
  }, [updateStateFor]);

  const handleJobSettled = useCallback(async (id: string) => {
    if (selectedIdRef.current === id) await refreshSelected(id);
    await refreshList();
  }, [refreshList, refreshSelected]);

  const handleJobError = useCallback((id: string, message: string) => {
    if (selectedIdRef.current === id) setError(message);
  }, []);

  const {
    connectionStatus,
    isStreaming,
    startJob,
    cancelJob: cancelRunJobControl,
    retry: retryRunConnection,
  } = useRunJob({
    selectedId,
    activeJob: state?.run_job,
    onEvent: handleEvent,
    onJobUpdate: handleJobUpdate,
    onSettled: handleJobSettled,
    onError: handleJobError,
  });

  const run = useCallback(async (id = selectedId) => {
    if (!id) return;
    setError("");
    try {
      await startJob(id, () => startNovelJob(id, "run"));
    } catch (err: unknown) {
      if (selectedIdRef.current === id) {
        setError(err instanceof Error ? err.message : "创作运行失败");
        await refreshSelected(id).catch(() => undefined);
      }
    }
  }, [refreshSelected, selectedId, startJob]);

  const resume = useCallback(async (review: ReviewSubmission | PlanningReviewSubmission) => {
    if (!selectedId) return;
    const id = selectedId;
    setError("");
    try {
      await startJob(id, () => startNovelJob(id, "resume", review));
    } catch (err: unknown) {
      if (selectedIdRef.current === id) {
        setError(err instanceof Error ? err.message : "恢复创作失败");
        await refreshSelected(id).catch(() => undefined);
      }
      throw err;
    }
  }, [refreshSelected, selectedId, startJob]);

  const cancelJob = useCallback(async () => {
    setError("");
    await cancelRunJobControl();
  }, [cancelRunJobControl]);

  const startBookRevision = useCallback(async (chapterNumber: number, feedback: string) => {
    if (!selectedId) return;
    const id = selectedId;
    setError("");
    try {
      await startJob(id, () => startBookRevisionJob(id, chapterNumber, feedback));
    } catch (err: unknown) {
      if (selectedIdRef.current === id) {
        setError(err instanceof Error ? err.message : "启动全书返修失败");
        await refreshSelected(id).catch(() => undefined);
      }
      throw err;
    }
  }, [refreshSelected, selectedId, startJob]);

  const generateCandidates = useCallback(async (count: number, instruction: string) => {
    if (!selectedId) return;
    const id = selectedId;
    setError("");
    try {
      await startJob(id, () => startCandidateGenerationJob(id, count, instruction));
    } catch (err: unknown) {
      if (selectedIdRef.current === id) {
        setError(err instanceof Error ? err.message : "候选稿生成失败");
        await refreshSelected(id).catch(() => undefined);
      }
      throw err;
    }
  }, [refreshSelected, selectedId, startJob]);

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
    const id = selectedId;
    const evaluation = await evaluateChapterVersion(id, state.current_chapter, versionNumber, includeJudge);
    updateStateFor(id, (current) => ({ ...current, evaluations: [evaluation, ...current.evaluations] }));
    return evaluation;
  }, [selectedId, state, updateStateFor]);

  const setEvaluationBaseline = useCallback(async (evaluationId: number) => {
    if (!selectedId || !state) throw new Error("尚未选择章节");
    const id = selectedId;
    const evaluation = await setChapterEvaluationBaseline(id, state.current_chapter, evaluationId);
    updateStateFor(id, (current) => ({
      ...current,
      evaluations: current.evaluations.map((item) => ({ ...item, is_baseline: item.id === evaluation.id })),
    }));
    return evaluation;
  }, [selectedId, state, updateStateFor]);

  const compareEvaluations = useCallback(async (fromVersion: number, toVersion: number) => {
    if (!selectedId || !state) throw new Error("尚未选择章节");
    return compareChapterEvaluations(selectedId, state.current_chapter, fromVersion, toVersion);
  }, [selectedId, state]);

  const updateCanon = useCallback(async (operation: CanonOperation) => {
    if (!selectedId) return;
    const id = selectedId;
    setError("");
    try {
      await startJob(id, () => startCanonJob(id, operation));
    } catch (err: unknown) {
      if (selectedIdRef.current === id) {
        setError(err instanceof Error ? err.message : "Canon 更新失败");
        await refreshSelected(id).catch(() => undefined);
      }
      throw err;
    }
  }, [refreshSelected, selectedId, startJob]);

  const updateBrief = useCallback(async (
    brief: CreativeBrief,
    changeSummary: string,
  ) => {
    if (!selectedId) throw new Error("尚未选择作品");
    const id = selectedId;
    setError("");
    try {
      const result = await updateCreativeBrief(
        id,
        brief,
        novel?.creative_brief_version,
        changeSummary,
      );
      if (selectedIdRef.current !== id) return result;
      setNovel(result);
      if (typeof listCreativeBriefVersions === "function") {
        const versions = await listCreativeBriefVersions(id);
        if (selectedIdRef.current !== id) return result;
        setCreativeBriefVersions(versions);
      }
      if (result.requires_revalidation) {
        await startJob(id, async () => {
          const job = await startNovelJob(id, "resume", { feedback: "recheck" });
          updateStateFor(id, (current) => ({
            ...current,
            creative_brief: result.creative_brief,
            creative_brief_version: result.creative_brief_version,
            creative_brief_review_required: true,
          }));
          return job;
        });
      } else {
        await refreshSelected(id);
      }
      return result;
    } catch (err: unknown) {
      if (selectedIdRef.current === id) {
        setError(err instanceof Error ? err.message : "保存创作约束失败");
        await refreshSelected(id).catch(() => undefined);
      }
      throw err;
    }
  }, [novel?.creative_brief_version, refreshSelected, selectedId, startJob, updateStateFor]);

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

  return { novels, novel, state, creativeBriefVersions, modelTraces, evaluationBenchmarks, memoryQuality, selectedId, setSelectedId, lastNode, error, isLoading, connectionStatus, isStreaming, deletingId, run, resume, cancelJob, retryRunConnection, startBookRevision, generateCandidates, updateCanon, updateBrief, loadModelTraces, loadEvaluationBenchmarks, runBenchmark, loadMemoryQuality, runMemoryQuality, rebuildMemoryIndex, exportNovel, importNovel, compareVersions, loadPlanningVersion, comparePlanningVersions, evaluateVersion, setEvaluationBaseline, compareEvaluations, addNovel, removeNovel };
}
