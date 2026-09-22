import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useReviewWorkflow } from "./useReviewWorkflow";

function deferred() {
  let resolve!: () => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<void>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

describe("useReviewWorkflow", () => {
  it("locks duplicate and conflicting commands before the first request settles", async () => {
    const pending = deferred();
    const onSubmit = vi.fn().mockReturnValue(pending.promise);
    const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));
    act(() => result.current.setFeedback("Revise"));
    let request!: Promise<void>;
    act(() => {
      request = result.current.submitRevision();
      void result.current.submitRevision();
      void result.current.approve();
      void result.current.replaceDraft({ feedback: "candidate", candidate_id: "c1" });
    });
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ feedback: "Revise", scene_number: undefined });
    expect(result.current.busyAction).toBe("revision");
    await act(async () => { pending.resolve(); await request; });
    expect(result.current.busyAction).toBe("");
  });

  it.each(["novel", "chapter"])("keeps a newer %s review and command intact when an old request settles", async (scope) => {
    const old = deferred();
    const current = deferred();
    const onSubmit = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const { result, rerender } = renderHook(
      ({ novelId, chapterNumber }) => useReviewWorkflow({ novelId, chapterNumber, onSubmit }),
      { initialProps: { novelId: "n1", chapterNumber: 2 } },
    );
    act(() => result.current.setFeedback("Old"));
    let oldRequest!: Promise<void>;
    act(() => { oldRequest = result.current.submitRevision(); });
    rerender({ novelId: scope === "novel" ? "n2" : "n1", chapterNumber: scope === "chapter" ? 3 : 2 });
    act(() => { result.current.selectScene(4); result.current.setFeedback("New"); });
    let currentRequest!: Promise<void>;
    act(() => { currentRequest = result.current.submitRevision(); });
    await act(async () => { old.resolve(); await oldRequest; });
    expect(result.current.feedback).toBe("New");
    expect(result.current.sceneNumber).toBe(4);
    expect(result.current.busyAction).toBe("revision");
    expect(result.current.focusRequest).toBe(0);
    await act(async () => { current.reject(new Error("Current failed")); await currentRequest; });
    expect(result.current.error).toBe("Current failed");
    expect(result.current.feedback).toBe("New");
  });

  it("preserves newer feedback and scope in the same chapter after a late completion", async () => {
    const pending = deferred();
    const onSubmit = vi.fn().mockReturnValue(pending.promise);
    const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));
    act(() => { result.current.selectScene(2); result.current.setFeedback("Original"); });
    let request!: Promise<void>;
    act(() => { request = result.current.submitRevision(); });
    act(() => { result.current.selectScene(3); result.current.setFeedback("Newer notes"); });
    await act(async () => { pending.resolve(); await request; });
    expect(result.current.feedback).toBe("Newer notes");
    expect(result.current.sceneNumber).toBe(3);
    expect(result.current.focusRequest).toBe(0);
  });

  it("keeps feedback and scope when submission fails", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("service unavailable"));
    const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));

    act(() => {
      result.current.selectScene(3);
      result.current.setFeedback("加强冲突");
    });
    await act(() => result.current.submitRevision());

    expect(result.current.sceneNumber).toBe(3);
    expect(result.current.feedback).toBe("加强冲突");
    expect(result.current.error).toBe("service unavailable");
    expect(result.current.busyAction).toBe("");
  });

  it("clears feedback and scope after a successful draft replacement", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));

    act(() => {
      result.current.selectScene(2);
      result.current.setFeedback("收紧节奏");
    });
    await act(() => result.current.replaceDraft({ feedback: "candidate", candidate_id: "c1" }));

    expect(result.current.feedback).toBe("");
    expect(result.current.sceneNumber).toBeUndefined();
    expect(result.current.focusRequest).toBe(1);
  });

  it("submits trimmed revision feedback for the selected scene", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));

    act(() => {
      result.current.selectScene(4);
      result.current.setFeedback("  增强转折  ");
    });
    await act(() => result.current.submitRevision());

    expect(onSubmit).toHaveBeenCalledWith({ feedback: "增强转折", scene_number: 4 });
    expect(result.current.feedback).toBe("");
    expect(result.current.sceneNumber).toBeUndefined();
    expect(result.current.focusRequest).toBe(1);
  });

  it("submits approval without treating it as a draft replacement", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useReviewWorkflow({ novelId: "n1", chapterNumber: 2, onSubmit }));

    await act(() => result.current.approve());

    expect(onSubmit).toHaveBeenCalledWith({ feedback: "approve" });
    expect(result.current.focusRequest).toBe(0);
  });

  it("resets local state only when the novel or chapter changes", () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const replacementSubmit = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ novelId, chapterNumber, submit }) => useReviewWorkflow({ novelId, chapterNumber, onSubmit: submit }),
      { initialProps: { novelId: "n1", chapterNumber: 2, submit: onSubmit } },
    );

    act(() => {
      result.current.setActiveTab("candidates");
      result.current.selectScene(2);
      result.current.setFeedback("保留这段");
    });
    rerender({ novelId: "n1", chapterNumber: 2, submit: replacementSubmit });
    expect(result.current.activeTab).toBe("candidates");
    expect(result.current.sceneNumber).toBe(2);
    expect(result.current.feedback).toBe("保留这段");

    rerender({ novelId: "n1", chapterNumber: 3, submit: replacementSubmit });
    expect(result.current.activeTab).toBe("decision");
    expect(result.current.sceneNumber).toBeUndefined();
    expect(result.current.feedback).toBe("");
    expect(result.current.error).toBe("");
    expect(result.current.focusRequest).toBe(0);

    act(() => {
      result.current.setActiveTab("versions");
      result.current.selectScene(1);
      result.current.setFeedback("换一本书");
    });
    rerender({ novelId: "n2", chapterNumber: 3, submit: replacementSubmit });
    expect(result.current.activeTab).toBe("decision");
    expect(result.current.sceneNumber).toBeUndefined();
    expect(result.current.feedback).toBe("");
  });
});
