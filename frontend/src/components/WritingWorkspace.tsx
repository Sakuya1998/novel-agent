import { ArrowRight, CheckCircle2 } from "lucide-react";
import type { CanonOperation, ChapterEvaluation, EvaluationComparison, Novel, ReviewSubmission, WorkbenchState } from "../types";
import type { RunConnectionStatus } from "../useRunJob";
import { ChapterReader } from "./ChapterReader";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { WritingStatusBar } from "./WritingStatusBar";

export interface WritingReaderFocus {
  novelId: string;
  chapterNumber?: number;
  sceneNumber?: number;
  request: number;
}

interface WritingWorkspaceProps {
  novel: Novel;
  state: WorkbenchState;
  connectionStatus: RunConnectionStatus;
  lastNode?: string;
  isStreaming: boolean;
  readerFocus?: WritingReaderFocus;
  onReaderFocusChange: (focus: WritingReaderFocus) => void;
  onRun: () => void | Promise<void>;
  onCancel: () => void | Promise<void>;
  onRetry: () => void;
  onSubmit: (review: ReviewSubmission) => Promise<void>;
  onApplyCanon?: (operation: CanonOperation) => Promise<void>;
  onGenerateCandidates?: (count: number, instruction: string) => Promise<void>;
  onCompareVersions?: (fromVersion: number, toVersion: number) => Promise<string>;
  onEvaluateVersion?: (versionNumber: number, includeJudge: boolean) => Promise<ChapterEvaluation>;
  onSetEvaluationBaseline?: (evaluationId: number) => Promise<ChapterEvaluation>;
  onCompareEvaluations?: (fromVersion: number, toVersion: number) => Promise<EvaluationComparison>;
  onOpenPlanning?: () => void;
  onOpenQuality?: () => void;
}

function WritingNextAction({
  state,
  onOpenPlanning,
  onOpenQuality,
}: Pick<WritingWorkspaceProps, "state" | "onOpenPlanning" | "onOpenQuality">) {
  if (state.status === "blueprint_review" || state.status === "scene_review") {
    return <aside className="next-panel review-required-panel">
      <div className="section-kicker">REVIEW REQUIRED</div>
      <CheckCircle2 size={21} />
      <h2>规划等待确认</h2>
      <p>批准当前蓝图或分镜后，正文创作才会继续。</p>
      <button className="primary-button full-width" type="button" onClick={onOpenPlanning}><span>前往审阅</span><ArrowRight size={15} /></button>
    </aside>;
  }

  if (state.status === "completed" && state.book_audit) {
    return <aside className="next-panel review-required-panel completed">
      <div className="section-kicker">MANUSCRIPT COMPLETE</div>
      <CheckCircle2 size={21} />
      <h2>全书已经完成</h2>
      <p>终审报告已生成，可以检查全书质量或发起返修。</p>
      <button className="secondary-button full-width" type="button" onClick={onOpenQuality}><span>查看终审</span><ArrowRight size={15} /></button>
    </aside>;
  }

  return <aside className="next-panel writing-next-action" aria-label="写作进度">
    <div className="section-kicker">WRITING WORKSPACE</div>
    <h2>{state.status === "running" ? "正在展开正文" : "稿件阅读"}</h2>
    <p>{state.status === "running" ? "状态栏会持续更新后台创作进度。" : "启动创作后，正文和章节进度会在这里展开。"}</p>
  </aside>;
}

export function WritingWorkspace({
  novel,
  state,
  connectionStatus,
  lastNode,
  isStreaming,
  readerFocus,
  onReaderFocusChange,
  onRun,
  onCancel,
  onRetry,
  onSubmit,
  onApplyCanon,
  onGenerateCandidates,
  onCompareVersions,
  onEvaluateVersion,
  onSetEvaluationBaseline,
  onCompareEvaluations,
  onOpenPlanning,
  onOpenQuality,
}: WritingWorkspaceProps) {
  const currentFocus = readerFocus?.novelId === novel.id && readerFocus?.chapterNumber === state.current_draft.chapter_number
    ? readerFocus : undefined;
  const disabled = state.status !== "running" && isStreaming;

  return <section className={`writing-workspace ${state.status === "human_review" ? "is-reviewing" : ""}`}>
    <WritingStatusBar
      status={state.status}
      job={state.run_job}
      lastNode={lastNode}
      connectionStatus={connectionStatus}
      currentChapter={state.current_chapter}
      totalChapters={state.total_chapters || novel.total_chapters}
      disabled={disabled}
      onRun={() => void onRun()}
      onCancel={() => void onCancel()}
      onRetry={onRetry}
    />
    <div className="writing-workspace-grid">
      <ChapterReader
        draft={state.current_draft}
        chapters={novel.chapters || []}
        status={state.status}
        selectedSceneNumber={currentFocus?.sceneNumber}
        focusRequest={currentFocus?.request}
      />
      {state.status === "human_review" ? <ReviewWorkspace
        novelId={novel.id}
        draft={state.current_draft}
        issues={state.issues ?? []}
        conflicts={state.conflicts ?? []}
        qualityReport={state.quality_report ?? undefined}
        persistenceError={state.persistence_error ?? ""}
        versions={state.versions ?? []}
        evaluations={state.evaluations ?? []}
        candidates={state.chapter_candidates ?? []}
        disabled={isStreaming}
        onSubmit={onSubmit}
        onApplyCanon={onApplyCanon}
        onGenerateCandidates={onGenerateCandidates}
        onCompareVersions={onCompareVersions}
        onEvaluateVersion={onEvaluateVersion}
        onSetEvaluationBaseline={onSetEvaluationBaseline}
        onCompareEvaluations={onCompareEvaluations}
        onFocusReader={(sceneNumber) => onReaderFocusChange({ novelId: novel.id, chapterNumber: state.current_draft.chapter_number, sceneNumber, request: (readerFocus?.request ?? 0) + 1 })}
      /> : <WritingNextAction state={state} onOpenPlanning={onOpenPlanning} onOpenQuality={onOpenQuality} />}
    </div>
  </section>;
}
