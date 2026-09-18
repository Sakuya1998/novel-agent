# Writing Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clear, recoverable writing and human-review workflow that keeps run status visible and makes whole-chapter, scene, candidate, and version actions unambiguous.

**Architecture:** Preserve the existing FastAPI job and review APIs. Extract persisted-job polling into `useRunJob`, keep review-only interaction state in `useReviewWorkflow`, and compose the writing surface through `WritingWorkspace`; existing candidate, version, evaluation, and reader components remain domain-focused children.

**Tech Stack:** React 19, TypeScript 7, Vite 8, Vitest 4, Testing Library, Lucide React, existing FastAPI persisted-job API

**Spec:** `docs/superpowers/specs/2026-09-17-writing-workflow-design.md`

## Global Constraints

- Preserve the current FastAPI request and response contracts.
- Continue using persisted run jobs and incremental event polling; do not add WebSocket transport.
- Do not change LangGraph topology, generation prompts, or persistence schemas.
- Do not modify runtime data under `data/`, `memory/`, or `output/`.
- Keep the current visual language; this work reorganizes workflow and state, not the entire application.
- Server state remains authoritative for jobs, drafts, candidates, versions, and evaluations.
- Client state is limited to connection state, tabs, selected scene, feedback, focus requests, and in-flight actions.
- Every task follows red-green-refactor and ends with its focused test suite passing.

## File Structure

- Create `frontend/src/useRunJob.ts`: persisted-job startup, polling, reconnecting, cancellation, and stale-response protection.
- Create `frontend/src/useRunJob.test.tsx`: hook tests for lifecycle, reconnection, cancellation, and project switching.
- Create `frontend/src/components/WritingStatusBar.tsx`: stable run state and connection controls.
- Create `frontend/src/components/WritingStatusBar.test.tsx`: status and action rendering tests.
- Create `frontend/src/useReviewWorkflow.ts`: chapter-scoped feedback, scope, tab, busy action, and submission state.
- Create `frontend/src/useReviewWorkflow.test.tsx`: review state retention and reset tests.
- Create `frontend/src/components/ReviewDecisionPanel.tsx`: controlled whole-chapter/scene decision form.
- Create `frontend/src/components/ReviewIssuesPanel.tsx`: consistency issues, repair actions, and quality gate.
- Create `frontend/src/components/ReviewWorkspace.tsx`: accessible tabs and fixed review decision area.
- Create `frontend/src/components/ReviewWorkspace.test.tsx`: integrated review interaction tests.
- Create `frontend/src/components/WritingWorkspace.tsx`: composition boundary for run, read, review, planning handoff, and completion states.
- Create `frontend/src/components/WritingWorkspace.test.tsx`: writing-state rendering tests.
- Modify `frontend/src/useWorkbench.ts`: delegate job lifecycle to `useRunJob` and expose connection status.
- Modify `frontend/src/useWorkbench.test.tsx`: retain workbench integration coverage with the extracted controller.
- Modify `frontend/src/components/ChapterReader.tsx`: render addressable scene sections and focus a selected scene.
- Create `frontend/src/components/ChapterReader.test.tsx`: scene rendering and focus tests.
- Modify `frontend/src/components/ChapterCandidatesPanel.tsx`: notify the parent after successful candidate adoption.
- Modify `frontend/src/components/VersionHistory.tsx`: notify the parent after successful restoration.
- Modify `frontend/src/App.tsx`: delegate the write view to `WritingWorkspace`.
- Modify `frontend/src/types.ts`: add client-only workflow types where they are shared by multiple components.
- Modify `frontend/src/styles.css`: writing status, reader scene, review tab, and decision-area styles.
- Modify `frontend/src/workspace.css`: responsive writing-workspace layout rules.
- Remove `frontend/src/components/ReviewPanel.tsx` and `frontend/src/components/ReviewPanel.test.tsx` after their behavior is covered by the new components.
- Remove `frontend/src/components/RunControlPanel.tsx` and `frontend/src/components/RunControlPanel.test.tsx` after `WritingStatusBar` and `WritingWorkspace` cover their behavior.

---

### Task 1: Extract Persisted Run Job Control

**Files:**
- Create: `frontend/src/useRunJob.ts`
- Create: `frontend/src/useRunJob.test.tsx`
- Modify: `frontend/src/useWorkbench.ts`
- Modify: `frontend/src/useWorkbench.test.tsx`

**Interfaces:**
- Consumes: `RunJob`, `RunJobEventsResponse`, `StreamEvent`, `getRunJobEvents`, and `cancelRunJob`.
- Produces: `RunConnectionStatus`, `UseRunJobOptions`, and `useRunJob()` returning `{ connectionStatus, isStreaming, startJob, cancelJob, retry }`.
- `startJob(novelId, createJob)` accepts `createJob: () => Promise<RunJob>` so run, resume, candidate, canon, and book-revision jobs share one lifecycle.

- [ ] **Step 1: Write failing lifecycle tests**

```tsx
it("reconnects after a transient polling failure without losing the event sequence", async () => {
  vi.mocked(getRunJobEvents)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ job: runningJob, events: [{ sequence: 4, payload: nodeEvent }] })
    .mockResolvedValueOnce({ job: completedJob, events: [] });

  const { result } = renderHook(() => useRunJob(options));
  await act(() => result.current.startJob("novel-1", async () => runningJob));

  await waitFor(() => expect(result.current.connectionStatus).toBe("idle"));
  expect(getRunJobEvents).toHaveBeenNthCalledWith(2, runningJob.id, 0, expect.any(AbortSignal));
  expect(getRunJobEvents).toHaveBeenNthCalledWith(3, runningJob.id, 4, expect.any(AbortSignal));
  expect(options.onEvent).toHaveBeenCalledWith("novel-1", nodeEvent);
  expect(options.onSettled).toHaveBeenCalledWith("novel-1");
});

it("drops events after the selected novel changes", async () => {
  const view = renderHook(({ selectedId }) => useRunJob({ ...options, selectedId }), {
    initialProps: { selectedId: "novel-1" },
  });
  view.rerender({ selectedId: "novel-2" });
  resolvePendingPoll({ job: completedJob, events: [{ sequence: 1, payload: nodeEvent }] });
  await waitFor(() => expect(options.onEvent).not.toHaveBeenCalled());
});
```

- [ ] **Step 2: Run the hook tests and verify the new module is missing**

Run: `cd frontend && npm test -- useRunJob.test.tsx`

Expected: FAIL because `./useRunJob` does not exist.

- [ ] **Step 3: Implement the run-job controller**

```ts
export type RunConnectionStatus = "idle" | "polling" | "reconnecting" | "failed";

export interface UseRunJobOptions {
  selectedId?: string;
  activeJob?: RunJob | null;
  onEvent: (novelId: string, event: StreamEvent) => void;
  onJobUpdate: (novelId: string, job: RunJob) => void;
  onSettled: (novelId: string) => Promise<void>;
  onError: (novelId: string, message: string) => void;
}

export function useRunJob(options: UseRunJobOptions) {
  // Own AbortController, sequence cursor, retry counter, active novel/job refs.
  // Retry five times with 350ms, 700ms, 1400ms, 2800ms, and 3000ms delays.
  // Validate both novel id and job id before applying every response.
  return { connectionStatus, isStreaming, startJob, cancelJob, retry };
}
```

`retry()` resumes polling the current persisted job from its last acknowledged sequence without creating a second job. Replace the polling refs and loop in `useWorkbench` with the controller. Route every job-producing command through `startJob`; preserve the current `handleEvent`, state updates, and post-settlement refresh behavior. Expose `retryRunConnection: retry` from `useWorkbench` for the status bar.

- [ ] **Step 4: Run focused hook and integration tests**

Run: `cd frontend && npm test -- useRunJob.test.tsx useWorkbench.test.tsx`

Expected: both test files PASS, including existing active-job reconnect and stale-project cases.

- [ ] **Step 5: Run type checking**

Run: `cd frontend && npm run typecheck`

Expected: PASS with no TypeScript errors.

- [ ] **Step 6: Commit the controller extraction**

```bash
git add frontend/src/useRunJob.ts frontend/src/useRunJob.test.tsx frontend/src/useWorkbench.ts frontend/src/useWorkbench.test.tsx
git commit -m "refactor(frontend): isolate persisted run jobs"
```

---

### Task 2: Add a Stable Writing Status Bar

**Files:**
- Create: `frontend/src/components/WritingStatusBar.tsx`
- Create: `frontend/src/components/WritingStatusBar.test.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `NovelStatus`, `RunJob`, `RunConnectionStatus`, current chapter counts, and existing `STAGES` labels.
- Produces: `WritingStatusBar` with `onRun`, `onCancel`, and `onRetry` commands.

- [ ] **Step 1: Write failing status rendering tests**

```tsx
it("shows the current node and stop action while running", async () => {
  const onCancel = vi.fn();
  render(<WritingStatusBar status="running" job={runningJob} connectionStatus="polling" currentChapter={2} totalChapters={8} disabled={false} onRun={vi.fn()} onCancel={onCancel} onRetry={vi.fn()} />);
  expect(screen.getByText("第 2 / 8 章")).toBeInTheDocument();
  expect(screen.getByText(/场景写作/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "停止运行" }));
  expect(onCancel).toHaveBeenCalledOnce();
});

it("announces reconnecting without replacing the last known node", () => {
  render(<WritingStatusBar status="running" job={runningJob} connectionStatus="reconnecting" currentChapter={2} totalChapters={8} disabled={false} onRun={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("连接中断，正在恢复");
  expect(screen.getByText(/场景写作/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the component test and verify failure**

Run: `cd frontend && npm test -- WritingStatusBar.test.tsx`

Expected: FAIL because `WritingStatusBar` does not exist.

- [ ] **Step 3: Implement status mapping and stable controls**

```tsx
const STATUS_COPY: Record<NovelStatus, { label: string; detail: string }> = {
  idle: { label: "准备开始", detail: "从世界观与角色设定开始" },
  running: { label: "创作进行中", detail: "后台任务正在执行" },
  interrupted: { label: "运行已中断", detail: "可从检查点继续" },
  blueprint_review: { label: "等待蓝图审阅", detail: "确认设定后继续" },
  scene_review: { label: "等待分镜审阅", detail: "确认场景计划后继续" },
  human_review: { label: "等待章节审稿", detail: "决定返修或通过定稿" },
  completed: { label: "创作完成", detail: "全部章节已定稿" },
  error: { label: "运行失败", detail: "检查错误后重新继续" },
  legacy_read_only: { label: "只读作品", detail: "缺少可恢复检查点" },
};
```

Render chapter progress, last known node, connection state, and exactly one primary control appropriate to the status. Keep a fixed minimum height so text changes do not shift the reader.

- [ ] **Step 4: Run component tests and type checking**

Run: `cd frontend && npm test -- WritingStatusBar.test.tsx && npm run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit the status bar**

```bash
git add frontend/src/components/WritingStatusBar.tsx frontend/src/components/WritingStatusBar.test.tsx frontend/src/types.ts frontend/src/styles.css
git commit -m "feat(frontend): add writing status bar"
```

---

### Task 3: Isolate Human Review Interaction State

**Files:**
- Create: `frontend/src/useReviewWorkflow.ts`
- Create: `frontend/src/useReviewWorkflow.test.tsx`
- Create: `frontend/src/components/ReviewDecisionPanel.tsx`
- Create: `frontend/src/components/ReviewDecisionPanel.test.tsx`

**Interfaces:**
- Consumes: `novelId`, `chapterNumber`, `ReviewSubmission`, and `onSubmit(review)`.
- Produces: `ReviewTab = "decision" | "issues" | "candidates" | "versions"`, `ReviewBusyAction`, and a controller containing scope, feedback, active tab, error, and commands.

- [ ] **Step 1: Write failing review-state tests**

```tsx
it("keeps feedback and scope when submission fails", async () => {
  const onSubmit = vi.fn().mockRejectedValue(new Error("service unavailable"));
  const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));
  act(() => { result.current.selectScene(3); result.current.setFeedback("加强冲突"); });
  await act(() => result.current.submitRevision());
  expect(result.current.sceneNumber).toBe(3);
  expect(result.current.feedback).toBe("加强冲突");
  expect(result.current.error).toBe("service unavailable");
});

it("clears feedback and scope after a successful draft replacement", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));
  act(() => { result.current.selectScene(2); result.current.setFeedback("收紧节奏"); });
  await act(() => result.current.replaceDraft({ feedback: "candidate", candidate_id: "c1" }));
  expect(result.current.feedback).toBe("");
  expect(result.current.sceneNumber).toBeUndefined();
  expect(result.current.focusRequest).toBe(1);
});
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd frontend && npm test -- useReviewWorkflow.test.tsx ReviewDecisionPanel.test.tsx`

Expected: FAIL because both modules are missing.

- [ ] **Step 3: Implement the review controller**

```ts
export type ReviewTab = "decision" | "issues" | "candidates" | "versions";
export type ReviewBusyAction = "" | "revision" | "approve" | "candidate" | "restore" | "canon";

export function useReviewWorkflow({ novelId, chapterNumber, onSubmit }: Options) {
  // Reset local state only when novelId or chapterNumber changes.
  // Preserve feedback after rejected promises.
  // Clear feedback/scope and increment focusRequest after successful replacements.
  return { activeTab, setActiveTab, sceneNumber, selectScene, feedback, setFeedback, busyAction, error, focusRequest, submitRevision, approve, replaceDraft };
}
```

- [ ] **Step 4: Implement the controlled decision form**

```tsx
<ReviewDecisionPanel
  scenePlan={draft.scene_plan ?? []}
  sceneNumber={workflow.sceneNumber}
  feedback={workflow.feedback}
  busyAction={workflow.busyAction}
  disabled={disabled}
  error={workflow.error}
  onSceneChange={workflow.selectScene}
  onFeedbackChange={workflow.setFeedback}
  onRevise={workflow.submitRevision}
  onApprove={workflow.approve}
/>
```

The panel must label the textarea as either whole-chapter or scene feedback and disable revision when feedback is blank.

- [ ] **Step 5: Run focused tests and type checking**

Run: `cd frontend && npm test -- useReviewWorkflow.test.tsx ReviewDecisionPanel.test.tsx && npm run typecheck`

Expected: PASS.

- [ ] **Step 6: Commit review-state isolation**

```bash
git add frontend/src/useReviewWorkflow.ts frontend/src/useReviewWorkflow.test.tsx frontend/src/components/ReviewDecisionPanel.tsx frontend/src/components/ReviewDecisionPanel.test.tsx
git commit -m "refactor(frontend): isolate review workflow state"
```

---

### Task 4: Make the Manuscript Scene-Aware

**Files:**
- Modify: `frontend/src/components/ChapterReader.tsx`
- Create: `frontend/src/components/ChapterReader.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: existing `Draft.scene_drafts`, optional `selectedSceneNumber`, and monotonically increasing `focusRequest`.
- Produces: addressable sections with `data-scene-number` and visible selected-scene treatment.

- [ ] **Step 1: Write failing scene focus tests**

```tsx
it("renders scene drafts as addressable manuscript sections", () => {
  render(<ChapterReader draft={draftWithScenes} chapters={[]} status="human_review" selectedSceneNumber={2} focusRequest={0} />);
  expect(screen.getByTestId("scene-1")).toHaveTextContent("第一场正文");
  expect(screen.getByTestId("scene-2")).toHaveAttribute("aria-current", "true");
});

it("scrolls the selected scene after a focus request", () => {
  const scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  const view = render(<ChapterReader draft={draftWithScenes} chapters={[]} status="human_review" selectedSceneNumber={2} focusRequest={0} />);
  view.rerender(<ChapterReader draft={draftWithScenes} chapters={[]} status="human_review" selectedSceneNumber={2} focusRequest={1} />);
  expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
});
```

- [ ] **Step 2: Run the reader tests and verify failure**

Run: `cd frontend && npm test -- ChapterReader.test.tsx`

Expected: FAIL because scene-aware props and sections are absent.

- [ ] **Step 3: Implement scene rendering with content fallback**

```tsx
const sceneRefs = useRef(new Map<number, HTMLElement>());
useEffect(() => {
  if (focusRequest > 0 && selectedSceneNumber) {
    sceneRefs.current.get(selectedSceneNumber)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}, [focusRequest, selectedSceneNumber]);
```

When `scene_drafts` exists, render each scene in order. When it is absent, continue rendering `draft.content` exactly as today.

- [ ] **Step 4: Run reader and existing review tests**

Run: `cd frontend && npm test -- ChapterReader.test.tsx ReviewPanel.test.tsx`

Expected: PASS before `ReviewPanel` is removed in Task 5.

- [ ] **Step 5: Commit scene-aware reading**

```bash
git add frontend/src/components/ChapterReader.tsx frontend/src/components/ChapterReader.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): focus manuscript scenes"
```

---

### Task 5: Build the Tabbed Review Workspace

**Files:**
- Create: `frontend/src/components/ReviewIssuesPanel.tsx`
- Create: `frontend/src/components/ReviewWorkspace.tsx`
- Create: `frontend/src/components/ReviewWorkspace.test.tsx`
- Modify: `frontend/src/components/ChapterCandidatesPanel.tsx`
- Modify: `frontend/src/components/ChapterCandidatesPanel.test.tsx`
- Modify: `frontend/src/components/VersionHistory.tsx`
- Modify: `frontend/src/components/VersionHistory.test.tsx`
- Modify: `frontend/src/styles.css`
- Remove: `frontend/src/components/ReviewPanel.tsx`
- Remove: `frontend/src/components/ReviewPanel.test.tsx`

**Interfaces:**
- Consumes: `useReviewWorkflow`, current draft, issues, conflicts, quality report, candidates, versions, and evaluations.
- Produces: accessible review tabs and a `ReviewDecisionPanel` that remains visible within the decision tab while its body scrolls.
- Candidate adoption and version restoration call `workflow.replaceDraft(...)` so successful replacement resets and focuses the reader.

- [ ] **Step 1: Write failing accessible-tab and workflow tests**

```tsx
it("switches among decision, issues, candidates, and versions", async () => {
  render(<ReviewWorkspace {...props} />);
  expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: /候选稿/ }));
  expect(screen.getByRole("tabpanel", { name: /候选稿/ })).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: /决定/ }));
  expect(screen.getByRole("textbox", { name: "整章修改意见" })).toBeVisible();
});

it("selects a scene and submits scene-scoped feedback", async () => {
  render(<ReviewWorkspace {...props} />);
  await userEvent.click(screen.getByRole("button", { name: /第 2 场/ }));
  await userEvent.type(screen.getByRole("textbox", { name: "第 2 场修改意见" }), "增强转折");
  await userEvent.click(screen.getByRole("button", { name: "重写此场景" }));
  expect(props.onSubmit).toHaveBeenCalledWith({ feedback: "增强转折", scene_number: 2 });
});
```

- [ ] **Step 2: Run review workspace tests and verify failure**

Run: `cd frontend && npm test -- ReviewWorkspace.test.tsx`

Expected: FAIL because `ReviewWorkspace` does not exist.

- [ ] **Step 3: Move issues and quality display into `ReviewIssuesPanel`**

Keep existing conflict evidence expansion, canon repair, revision-feedback repair, severity labels, and quality gate scores. Accept controlled `disabled` and `busyAction` props rather than owning submission state.

- [ ] **Step 4: Implement accessible review tabs**

```tsx
<div className="review-tabs" role="tablist" aria-label="章节审稿工具">
  {tabs.map((tab) => <button key={tab.id} role="tab" aria-selected={activeTab === tab.id} aria-controls={`review-${tab.id}`} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}
</div>
<section id={`review-${activeTab}`} role="tabpanel" aria-label={activeLabel} className={`review-tab-panel ${activeTab === "decision" ? "has-decision-dock" : ""}`}>
  {activeContent}
</section>
```

Tabs are `decision`, `issues`, `candidates`, and `versions`; hide only supporting tabs whose source data and command are both unavailable. The decision tab is always present and renders `ReviewDecisionPanel` in a sticky dock inside that tab.

- [ ] **Step 5: Route candidate and version replacements through the workflow**

Add `onSelected?: () => void` to `ChapterCandidatesPanel` and `onRestored?: () => void` to `VersionHistory`. Invoke each callback only after the corresponding promise resolves. In `ReviewWorkspace`, pass callbacks that return to the decision tab and request reader focus.

- [ ] **Step 6: Remove the old monolithic review component**

Delete `ReviewPanel.tsx` and its test after all behaviors are represented in `ReviewWorkspace.test.tsx`, `ReviewDecisionPanel.test.tsx`, and the existing child tests.

- [ ] **Step 7: Run all review-related tests and type checking**

Run: `cd frontend && npm test -- ReviewWorkspace.test.tsx ReviewDecisionPanel.test.tsx ChapterCandidatesPanel.test.tsx VersionHistory.test.tsx ChapterEvaluationPanel.test.tsx && npm run typecheck`

Expected: PASS.

- [ ] **Step 8: Commit the review workspace**

```bash
git add frontend/src/components frontend/src/styles.css
git commit -m "feat(frontend): unify chapter review workflow"
```

---

### Task 6: Integrate the Writing Workspace

**Files:**
- Create: `frontend/src/components/WritingWorkspace.tsx`
- Create: `frontend/src/components/WritingWorkspace.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/useWorkbench.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/workspace.css`
- Remove: `frontend/src/components/RunControlPanel.tsx`
- Remove: `frontend/src/components/RunControlPanel.test.tsx`

**Interfaces:**
- Consumes: selected `Novel`, `WorkbenchState`, `connectionStatus`, `lastNode`, and existing workbench commands.
- Produces: one component boundary for every `workspaceView === "write"` state.

- [ ] **Step 1: Write failing composition tests**

```tsx
it("shows reader, status, and review workspace during human review", () => {
  render(<WritingWorkspace {...props} state={humanReviewState} />);
  expect(screen.getByText("等待章节审稿")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "第 2 章审查" })).toBeInTheDocument();
  expect(screen.getByText("待审查正文")).toBeInTheDocument();
});

it("hands planning review back to the planning workspace", async () => {
  const onOpenPlanning = vi.fn();
  render(<WritingWorkspace {...props} state={sceneReviewState} onOpenPlanning={onOpenPlanning} />);
  await userEvent.click(screen.getByRole("button", { name: "前往审阅" }));
  expect(onOpenPlanning).toHaveBeenCalledOnce();
});
```

- [ ] **Step 2: Run the composition test and verify failure**

Run: `cd frontend && npm test -- WritingWorkspace.test.tsx`

Expected: FAIL because `WritingWorkspace` does not exist.

- [ ] **Step 3: Implement the writing composition boundary**

```tsx
<section className={`writing-workspace ${state.status === "human_review" ? "is-reviewing" : ""}`}>
  <WritingStatusBar {...statusProps} />
  <div className="writing-workspace-grid">
    <ChapterReader {...readerProps} />
    {state.status === "human_review" ? <ReviewWorkspace {...reviewProps} /> : <WritingNextAction {...nextActionProps} />}
  </div>
</section>
```

Keep planning-review and completed-book handoff messages, but render them inside the stable writing grid. `WritingNextAction` can remain private to `WritingWorkspace.tsx` because it has no independent domain behavior.

- [ ] **Step 4: Replace the `App.tsx` write-view branch**

Pass commands from `useWorkbench` into `WritingWorkspace`, including `retryRunConnection`. Remove direct imports of `ChapterReader`, `ReviewPanel`, and `RunControlPanel` from `App.tsx`, then delete the unused `RunControlPanel` module and its test. Preserve all non-writing views and dialogs unchanged.

- [ ] **Step 5: Add responsive layout rules**

Desktop: status bar spans the full writing width, reader is `minmax(0, 1fr)`, review is constrained to `360px`–`430px`.

At `max-width: 980px`: use a single column and place review after the reader.

At `max-width: 680px`: decision dock returns to normal flow, tabs scroll horizontally, and no fixed element overlaps the soft keyboard.

- [ ] **Step 6: Run workspace, app, and existing navigation tests**

Run: `cd frontend && npm test -- WritingWorkspace.test.tsx WorkspaceNav.test.tsx useWorkbench.test.tsx && npm run typecheck`

Expected: PASS.

- [ ] **Step 7: Commit workspace integration**

```bash
git add frontend/src/App.tsx frontend/src/useWorkbench.ts frontend/src/types.ts frontend/src/components/WritingWorkspace.tsx frontend/src/components/WritingWorkspace.test.tsx frontend/src/components/RunControlPanel.tsx frontend/src/components/RunControlPanel.test.tsx frontend/src/styles.css frontend/src/workspace.css
git commit -m "feat(frontend): integrate writing workflow workspace"
```

---

### Task 7: Complete Regression and Browser Verification

**Files:**
- Modify: focused frontend tests only when verification reveals a missing assertion.
- Modify: `README.md` only if user-visible workflow instructions no longer match the application.

**Interfaces:**
- Consumes: all components and hooks delivered by Tasks 1–6.
- Produces: verified desktop/mobile workflow with no backend contract change.

- [ ] **Step 1: Run the full frontend suite**

Run: `cd frontend && npm test`

Expected: all test files PASS with zero failed tests.

- [ ] **Step 2: Run TypeScript and production build checks**

Run: `cd frontend && npm run typecheck && npm run build`

Expected: both commands exit 0 and Vite emits `frontend/dist`.

- [ ] **Step 3: Run backend compatibility checks**

Run: `python -m pytest -q`

Expected: all backend tests PASS. If the environment lacks test dependencies, install the declared development extra with `python -m pip install -e ".[dev]"`, then rerun.

Run: `ruff check src tests scripts main.py`

Expected: `All checks passed!`

Run: `python -m scripts.run_evaluations`

Expected: exit 0 with no regression exceeding the configured threshold.

- [ ] **Step 4: Start local services for browser verification**

Run in terminal 1: `uvicorn novel_agent.api.server:app --reload`

Run in terminal 2: `cd frontend && npm run dev -- --host 127.0.0.1`

Expected: API responds on `http://127.0.0.1:8000/readyz` and the workbench loads from the Vite URL.

- [ ] **Step 5: Verify desktop workflow at 1440x900**

Verify: stable status bar; readable manuscript; accessible review tabs; whole-chapter and scene scope selection; visible decision controls; candidate comparison; version comparison; no overlap or horizontal clipping.

- [ ] **Step 6: Verify mobile workflow at 390x844**

Verify: single-column order; horizontally scrollable tabs; decision controls in document flow; no text/button overflow; candidate comparison remains navigable.

- [ ] **Step 7: Verify dynamic behavior**

Exercise one persisted run through waiting review, a scene-scoped revision, and approval. Reload once during a running task and confirm reconnection. Switch novels during polling and confirm the first novel's events do not change the second novel.

- [ ] **Step 8: Review the final diff**

Run: `git diff main...HEAD --check && git diff main...HEAD --stat && git status --short`

Expected: no whitespace errors, only planned source/test/documentation changes, and a clean working tree after the final commit.

- [ ] **Step 9: Commit verification-only adjustments if needed**

```bash
git add frontend/src README.md
git commit -m "test(frontend): cover writing workflow transitions"
```

Skip this commit when verification requires no file changes.
