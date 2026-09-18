import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StageRail } from "./StageRail";

afterEach(cleanup);

describe("StageRail", () => {
  it("shows the final audit as the current stage after the novel completes", () => {
    render(<StageRail status="completed" currentPhase="" />);

    expect(screen.getByText("当前：全书终审")).toBeInTheDocument();
  });
});
