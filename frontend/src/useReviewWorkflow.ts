import { useCallback, useEffect, useRef, useState } from "react";
import type { ReviewSubmission } from "./types";

export type ReviewTab = "decision" | "issues" | "candidates" | "versions";
export type ReviewBusyAction = "" | "revision" | "approve" | "candidate" | "generate" | "restore" | "canon";
export type ReviewWorkflow = ReturnType<typeof useReviewWorkflow>;

export interface UseReviewWorkflowOptions {
  novelId: string;
  chapterNumber: number;
  onSubmit: (review: ReviewSubmission) => Promise<void>;
}

function submissionError(reason: unknown) {
  return reason instanceof Error ? reason.message : "审稿提交失败";
}

export function useReviewWorkflow({ novelId, chapterNumber, onSubmit }: UseReviewWorkflowOptions) {
  const [activeTab, setActiveTab] = useState<ReviewTab>("decision");
  const [sceneNumber, setSceneNumber] = useState<number>();
  const [feedback, updateFeedback] = useState("");
  const [busyAction, setBusyAction] = useState<ReviewBusyAction>("");
  const [error, setError] = useState("");
  const [focusRequest, setFocusRequest] = useState(0);
  const busyActionRef = useRef<ReviewBusyAction>("");
  const scopeVersionRef = useRef(0);
  const editVersionRef = useRef(0);

  const setFeedback = useCallback((value: string) => {
    editVersionRef.current += 1;
    updateFeedback(value);
  }, []);

  const selectScene = useCallback((value: number | undefined) => {
    editVersionRef.current += 1;
    setSceneNumber(value);
  }, []);

  useEffect(() => {
    scopeVersionRef.current += 1;
    busyActionRef.current = "";
    setActiveTab("decision");
    setSceneNumber(undefined);
    updateFeedback("");
    setBusyAction("");
    setError("");
    setFocusRequest(0);
  }, [novelId, chapterNumber]);

  const runAction = useCallback(async (
    action: Exclude<ReviewBusyAction, "">,
    command: () => Promise<void>,
    onSuccess?: () => void,
    propagateError = false,
  ) => {
    if (busyActionRef.current) return;

    const scopeVersion = scopeVersionRef.current;
    busyActionRef.current = action;
    setBusyAction(action);
    setError("");
    try {
      await command();
      if (scopeVersion !== scopeVersionRef.current) return;
      onSuccess?.();
    } catch (reason) {
      if (scopeVersion === scopeVersionRef.current) setError(submissionError(reason));
      if (propagateError && scopeVersion === scopeVersionRef.current) throw reason;
    } finally {
      if (scopeVersion === scopeVersionRef.current && busyActionRef.current === action) {
        busyActionRef.current = "";
        setBusyAction("");
      }
    }
  }, []);

  const submit = useCallback((
    review: ReviewSubmission,
    action: Exclude<ReviewBusyAction, "">,
    replacesDraft: boolean,
    propagateError = false,
    onReplaced?: () => void,
  ) => {
    const editVersion = editVersionRef.current;
    return runAction(action, () => onSubmit(review), () => {
      if (replacesDraft && editVersion === editVersionRef.current) {
        updateFeedback("");
        setSceneNumber(undefined);
        setFocusRequest((request) => request + 1);
        onReplaced?.();
      }
    }, propagateError);
  }, [onSubmit, runAction]);

  const submitRevision = useCallback(
    () => submit({ feedback: feedback.trim(), scene_number: sceneNumber }, "revision", true),
    [feedback, sceneNumber, submit],
  );

  const approve = useCallback(
    () => submit({ feedback: "approve" }, "approve", false),
    [submit],
  );

  const replaceDraft = useCallback((review: ReviewSubmission, onReplaced?: () => void) => {
    const action = review.candidate_id
      ? "candidate"
      : review.version_number !== undefined
        ? "restore"
        : "revision";
    return submit(review, action, true, true, onReplaced);
  }, [submit]);

  return {
    activeTab,
    setActiveTab,
    sceneNumber,
    selectScene,
    feedback,
    setFeedback,
    busyAction,
    error,
    focusRequest,
    submitRevision,
    approve,
    replaceDraft,
    runAction,
  };
}
