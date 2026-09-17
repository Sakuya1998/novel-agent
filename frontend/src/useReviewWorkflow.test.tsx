import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useReviewWorkflow } from "./useReviewWorkflow";

describe("useReviewWorkflow", () => {
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
