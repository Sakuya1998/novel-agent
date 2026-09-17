import { useCallback, useEffect, useRef, useState } from "react";
import type { ReviewSubmission } from "./types";

export type ReviewTab = "decision" | "issues" | "candidates" | "versions";
export type ReviewBusyAction = "" | "revision" | "approve" | "candidate" | "restore" | "canon";

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
  const [feedback, setFeedback] = useState("");
  const [busyAction, setBusyAction] = useState<ReviewBusyAction>("");
  const [error, setError] = useState("");
  const [focusRequest, setFocusRequest] = useState(0);
  const busyActionRef = useRef<ReviewBusyAction>("");
  const scopeVersionRef = useRef(0);

  useEffect(() => {
    scopeVersionRef.current += 1;
    busyActionRef.current = "";
    setActiveTab("decision");
    setSceneNumber(undefined);
    setFeedback("");
    setBusyAction("");
    setError("");
    setFocusRequest(0);
  }, [novelId, chapterNumber]);

  const submit = useCallback(async (
    review: ReviewSubmission,
    action: ReviewBusyAction,
    replacesDraft: boolean,
  ) => {
    if (busyActionRef.current) return;

    const scopeVersion = scopeVersionRef.current;
    busyActionRef.current = action;
    setBusyAction(action);
    setError("");
    try {
      await onSubmit(review);
      if (scopeVersion !== scopeVersionRef.current) return;
      if (replacesDraft) {
        setFeedback("");
        setSceneNumber(undefined);
        setFocusRequest((request) => request + 1);
      }
    } catch (reason) {
      if (scopeVersion === scopeVersionRef.current) setError(submissionError(reason));
    } finally {
      if (scopeVersion === scopeVersionRef.current && busyActionRef.current === action) {
        busyActionRef.current = "";
        setBusyAction("");
      }
    }
  }, [onSubmit]);

  const submitRevision = useCallback(
    () => submit({ feedback: feedback.trim(), scene_number: sceneNumber }, "revision", true),
    [feedback, sceneNumber, submit],
  );

  const approve = useCallback(
    () => submit({ feedback: "approve" }, "approve", false),
    [submit],
  );

  const replaceDraft = useCallback((review: ReviewSubmission) => {
    const action: ReviewBusyAction = review.candidate_id
      ? "candidate"
      : review.version_number !== undefined
        ? "restore"
        : "revision";
    return submit(review, action, true);
  }, [submit]);

  return {
    activeTab,
    setActiveTab,
    sceneNumber,
    selectScene: setSceneNumber,
    feedback,
    setFeedback,
    busyAction,
    error,
    focusRequest,
    submitRevision,
    approve,
    replaceDraft,
  };
}
