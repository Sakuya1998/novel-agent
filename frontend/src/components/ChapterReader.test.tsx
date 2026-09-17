import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Draft } from "../types";
import { ChapterReader } from "./ChapterReader";

const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (originalScrollIntoView) {
    Object.defineProperty(Element.prototype, "scrollIntoView", originalScrollIntoView);
  } else {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

const draftWithScenes: Draft = {
  chapter_number: 1,
  title: "雾中来客",
  scene_drafts: [
    { scene_number: 1, content: "第一场正文" },
    { scene_number: 2, content: "第二场正文" },
  ],
};

describe("ChapterReader", () => {
  it("renders scene drafts as addressable manuscript sections", () => {
    render(<ChapterReader
      draft={draftWithScenes}
      chapters={[]}
      status="human_review"
      selectedSceneNumber={2}
      focusRequest={0}
    />);

    expect(screen.getByTestId("scene-1")).toHaveTextContent("第一场正文");
    expect(screen.getByTestId("scene-1")).toHaveAttribute("data-scene-number", "1");
    expect(screen.getByTestId("scene-2")).toHaveAttribute("aria-current", "true");
  });

  it("scrolls the selected scene after a focus request", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const view = render(<ChapterReader
      draft={draftWithScenes}
      chapters={[]}
      status="human_review"
      selectedSceneNumber={2}
      focusRequest={0}
    />);

    view.rerender(<ChapterReader
      draft={draftWithScenes}
      chapters={[]}
      status="human_review"
      selectedSceneNumber={2}
      focusRequest={1}
    />);

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  it("keeps rendering aggregate content when scene drafts are absent", () => {
    render(<ChapterReader
      draft={{ chapter_number: 1, content: "旧版完整正文" }}
      chapters={[]}
      status="complete"
    />);

    expect(screen.getByText("旧版完整正文")).toHaveClass("manuscript-content");
  });
});
