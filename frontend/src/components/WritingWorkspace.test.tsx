import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Novel, ReviewSubmission, WorkbenchState } from "../types";
import { WritingWorkspace as WritingWorkspaceView } from "./WritingWorkspace";
import { useReviewWorkflow } from "../useReviewWorkflow";
import App from "../App";
import { useWorkbench } from "../useWorkbench";

vi.mock("../useWorkbench", () => ({ useWorkbench: vi.fn() }));
vi.mock("../useServiceStatus", () => ({ useServiceStatus: () => "ready" }));
vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  getAuthStatus: vi.fn().mockResolvedValue({ enabled: false, user: null }),
  getNovelCanon: vi.fn().mockResolvedValue({ version: 1, world_facts: [], characters: {}, aliases: {}, timeline: [], facts: [], narrative_threads: [], audit: [] }),
}));

const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");

function WritingWorkspace({ onSubmit, ...props }: Omit<React.ComponentProps<typeof WritingWorkspaceView>, "reviewWorkflow"> & {
  onSubmit: (review: ReviewSubmission) => Promise<void>;
}) {
  const reviewWorkflow = useReviewWorkflow({ novelId: props.novel.id, chapterNumber: props.state.current_draft.chapter_number ?? 0, onSubmit });
  return <WritingWorkspaceView {...props} reviewWorkflow={reviewWorkflow} />;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  if (originalScrollIntoView) Object.defineProperty(Element.prototype, "scrollIntoView", originalScrollIntoView);
  else Reflect.deleteProperty(Element.prototype, "scrollIntoView");
});

const novel: Novel = {
  id: "novel-1",
  title: "雾都来信",
  genre: "悬疑",
  inspiration: "一封无法寄出的信",
  style: "克制",
  total_chapters: 8,
  chapters: [],
};

const baseState: WorkbenchState = {
  novel_id: novel.id,
  status: "human_review",
  current_chapter: 2,
  current_phase: "human_review",
  chapters_done: 1,
  total_chapters: 8,
  next: [],
  review_node: "human_review",
  planning_review_enabled: true,
  world_bible: "",
  characters: [],
  outline: [],
  chapter_plan: {},
  scene_plan: [],
  planning_versions: [],
  chapter_candidates: [],
  current_draft: { chapter_number: 2, title: "雾中来客", content: "待审查正文" },
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
};

const props = {
  novel,
  state: baseState,
  connectionStatus: "idle" as const,
  lastNode: undefined,
  isStreaming: false,
  onReaderFocusChange: vi.fn(),
  onRun: vi.fn(),
  onCancel: vi.fn(),
  onRetry: vi.fn(),
  onSubmit: vi.fn().mockResolvedValue(undefined),
  onApplyCanon: vi.fn().mockResolvedValue(undefined),
  onGenerateCandidates: vi.fn().mockResolvedValue(undefined),
  onCompareVersions: vi.fn().mockResolvedValue(""),
  onEvaluateVersion: vi.fn().mockResolvedValue(undefined),
  onSetEvaluationBaseline: vi.fn().mockResolvedValue(undefined),
  onCompareEvaluations: vi.fn().mockResolvedValue(undefined),
};

const restorationState: WorkbenchState = {
  ...baseState,
  current_draft: {
    ...baseState.current_draft,
    scene_plan: [{ scene_number: 2, goal: "摆脱追兵", conflict: "道路封锁", turn: "进入暗巷", location: "长街", characters: ["林寒"], emotion: "急迫", estimated_words: 600 }],
    scene_drafts: [{ scene_number: 2, content: "第二场正文" }],
  },
  versions: [{ id: 1, chapter_number: 2, version_number: 1, source: "initial", word_count: 10, preview: "初稿", created_at: "2026-09-17" }],
};

function mockWorkbench(selectedNovel = novel, state = restorationState) {
  vi.mocked(useWorkbench).mockReturnValue({
    novels: [novel, { ...novel, id: "novel-2", title: "另一部作品" }],
    novel: selectedNovel, state, selectedId: selectedNovel.id,
    creativeBriefVersions: [], modelTraces: [], evaluationBenchmarks: [], memoryQuality: { latest: null, runs: [] },
    lastNode: undefined, error: "", isLoading: false, connectionStatus: "idle", isStreaming: false, deletingId: undefined,
    setSelectedId: vi.fn(), run: props.onRun, resume: props.onSubmit, cancelJob: props.onCancel,
    retryRunConnection: props.onRetry, generateCandidates: props.onGenerateCandidates,
    updateCanon: props.onApplyCanon, compareVersions: props.onCompareVersions,
    evaluateVersion: props.onEvaluateVersion, setEvaluationBaseline: props.onSetEvaluationBaseline,
    compareEvaluations: props.onCompareEvaluations, startBookRevision: vi.fn(), updateBrief: vi.fn(),
    loadModelTraces: vi.fn(), loadEvaluationBenchmarks: vi.fn(), runBenchmark: vi.fn(),
    loadMemoryQuality: vi.fn(), runMemoryQuality: vi.fn(), rebuildMemoryIndex: vi.fn(),
    exportNovel: vi.fn(), importNovel: vi.fn(), loadPlanningVersion: vi.fn(), comparePlanningVersions: vi.fn(),
    addNovel: vi.fn(), removeNovel: vi.fn(),
  });
}

describe("App writing navigation", () => {
  it("clears a planning submission error when another novel has the same review stage", async () => {
    const planningState: WorkbenchState = { ...baseState, status: "blueprint_review", review_node: "blueprint_review" };
    props.onSubmit.mockRejectedValueOnce(new Error("Previous novel failed"));
    mockWorkbench(novel, planningState);
    const view = render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "批准并继续" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Previous novel failed");
    const nextNovel = { ...novel, id: "novel-2" };
    mockWorkbench(nextNovel, { ...planningState, novel_id: nextNovel.id });
    view.rerender(<App />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the canon dialog locked while candidate creation is pending after navigation", async () => {
    let resolve!: () => void;
    const pending = new Promise<void>((done) => { resolve = done; });
    props.onGenerateCandidates.mockReturnValueOnce(pending);
    mockWorkbench();
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "候选稿" }));
    await userEvent.click(screen.getByRole("button", { name: "生成候选稿" }));
    await userEvent.click(screen.getByRole("tab", { name: "设定" }));
    await userEvent.click(screen.getByRole("button", { name: /事实与叙事线程/ }));
    expect(await screen.findByRole("button", { name: "新增" })).toBeDisabled();
    await act(async () => { resolve(); await pending; });
    expect(screen.getByRole("button", { name: "新增" })).toBeEnabled();
  });

  it("keeps review decisions locked while a canon dialog command is pending", async () => {
    let resolve!: () => void;
    const pending = new Promise<void>((done) => { resolve = done; });
    props.onApplyCanon.mockReturnValueOnce(pending);
    mockWorkbench();
    render(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "设定" }));
    await userEvent.click(screen.getByRole("button", { name: /事实与叙事线程/ }));
    await userEvent.click(await screen.findByRole("button", { name: "新增" }));
    await userEvent.type(screen.getByRole("textbox", { name: "事实路径" }), "city");
    await userEvent.type(screen.getByRole("textbox", { name: "事实内容" }), "Fog");
    await userEvent.type(screen.getByRole("textbox", { name: "变更原因" }), "Consistency");
    await userEvent.click(screen.getByRole("button", { name: "保存事实" }));
    await userEvent.click(screen.getByRole("button", { name: "关闭 Canon" }));
    await userEvent.click(screen.getByRole("tab", { name: "写作" }));
    expect(screen.getByRole("button", { name: "通过定稿" })).toBeDisabled();
    await act(async () => { resolve(); await pending; });
    expect(screen.getByRole("button", { name: "通过定稿" })).toBeEnabled();
  });

  it.each(["设定", "质量", "规划"])("preserves feedback, scope, and reader focus after leaving for %s and returning", async (destination) => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    mockWorkbench();
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "第 2 场修改意见" }), "Keep these notes");
    expect(screen.getByTestId("scene-2")).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("textbox", { name: "第 2 场修改意见" })).toHaveValue("Keep these notes");
    expect(screen.getByRole("button", { name: /第 2 场/ })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("tab", { name: destination }));
    expect(screen.queryByTestId("scene-2")).not.toBeInTheDocument();
    scrollIntoView.mockClear();
    await userEvent.click(screen.getByRole("tab", { name: "写作" }));

    expect(screen.getByTestId("scene-2")).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("textbox", { name: "第 2 场修改意见" })).toHaveValue("Keep these notes");
    expect(screen.getByRole("button", { name: /第 2 场/ })).toHaveAttribute("aria-pressed", "true");
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(scrollIntoView.mock.instances[0]).toBe(screen.getByTestId("scene-2"));

    scrollIntoView.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "整章修改" }));
    expect(screen.getByTestId("scene-2")).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toHaveValue("Keep these notes");
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(scrollIntoView.mock.instances[0]).toBe(screen.getByRole("article"));
  });

  it.each(["novel", "chapter"])("does not apply saved reader focus to a different %s", async (scope) => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    mockWorkbench();
    const view = render(<App />);
    await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "第 2 场修改意见" }), "Old notes");
    expect(screen.getByTestId("scene-2")).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("tab", { name: "设定" }));

    const nextNovel = scope === "novel" ? { ...novel, id: "novel-2" } : novel;
    mockWorkbench(nextNovel, { ...restorationState, novel_id: nextNovel.id,
      current_draft: { ...restorationState.current_draft, chapter_number: scope === "chapter" ? 3 : 2 },
    });
    scrollIntoView.mockClear();
    view.rerender(<App />);
    await userEvent.click(screen.getByRole("tab", { name: "写作" }));

    expect(screen.getByTestId("scene-2")).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("textbox", { name: "整章修改意见" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "整章修改" })).toHaveAttribute("aria-pressed", "true");
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});

describe("WritingWorkspace", () => {
  it("shows reader, status, and review workspace during human review", () => {
    render(<WritingWorkspace {...props} />);

    expect(screen.getByText("等待章节审稿")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "第 2 章审查" })).toBeInTheDocument();
    expect(screen.getByText("待审查正文")).toBeInTheDocument();
  });

  it("hands planning review back to the planning workspace", async () => {
    const onOpenPlanning = vi.fn();
    render(<WritingWorkspace {...props} state={{ ...baseState, status: "scene_review", review_node: "scene_review" }} onOpenPlanning={onOpenPlanning} />);

    await userEvent.click(screen.getByRole("button", { name: "前往审阅" }));
    expect(onOpenPlanning).toHaveBeenCalledOnce();
  });

  it("focuses manuscript top and clears the scene highlight after restoring a version", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    mockWorkbench();
    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
    scrollIntoView.mockClear();
    await userEvent.click(screen.getByRole("tab", { name: /版本/ }));
    await userEvent.click(screen.getByRole("button", { name: "恢复 v1" }));

    expect(props.onSubmit).toHaveBeenCalledWith({ feedback: "restore", version_number: 1 });
    expect(screen.getByTestId("scene-2")).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("article")).toHaveFocus();
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(scrollIntoView.mock.instances[0]).toBe(screen.getByRole("article"));
  });

  it("keeps stop available while streaming and connects run and retry commands", async () => {
    const view = render(<WritingWorkspace {...props} state={{ ...baseState, status: "idle" }} />);
    await userEvent.click(screen.getByRole("button", { name: "开始创作" }));
    expect(props.onRun).toHaveBeenCalledOnce();

    view.rerender(<WritingWorkspace {...props} state={{ ...baseState, status: "running" }} isStreaming connectionStatus="reconnecting" lastNode="scene_writer" />);
    expect(screen.getByText("场景写作")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("连接中断，正在恢复");
    await userEvent.click(screen.getByRole("button", { name: "停止运行" }));
    expect(props.onCancel).toHaveBeenCalledOnce();

    view.rerender(<WritingWorkspace {...props} state={{ ...baseState, status: "running" }} isStreaming connectionStatus="failed" lastNode="scene_writer" />);
    await userEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(props.onRetry).toHaveBeenCalledOnce();
  });

  it("hands a completed book with an audit to the quality workspace", async () => {
    const onOpenQuality = vi.fn();
    render(<WritingWorkspace {...props} state={{ ...baseState, status: "completed", book_audit: {
      schema_version: "1", rubric_version: "1", manuscript_hash: "hash", deterministic_scores: {}, judge_scores: {}, overall_score: 80, findings: [], revision_priorities: [],
    } }} onOpenQuality={onOpenQuality} />);
    await userEvent.click(screen.getByRole("button", { name: "查看终审" }));
    expect(onOpenQuality).toHaveBeenCalledOnce();
    expect(screen.queryByRole("heading", { name: "第 2 章审查" })).not.toBeInTheDocument();
  });

  it("allows reconnection when polling fails after cancellation was requested", async () => {
    render(<WritingWorkspace {...props} isStreaming connectionStatus="failed" state={{ ...baseState, status: "running", run_job: {
      id: "job-1", novel_id: novel.id, action: "run", status: "running", request: {}, current_node: "scene_writer", error: "", cancel_requested: true, created_at: "2026-09-17", updated_at: "2026-09-17",
    } }} />);
    await userEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(props.onRetry).toHaveBeenCalledOnce();
  });
});
