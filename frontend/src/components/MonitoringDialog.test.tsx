import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditLog, MonitoringSummary, ReadinessReport } from "../types";

const api = vi.hoisted(() => ({
  getReadiness: vi.fn(),
  getMonitoringSummary: vi.fn(),
  listAuditLogs: vi.fn(),
}));

vi.mock("../api", () => api);

import { MonitoringDialog } from "./MonitoringDialog";

const readiness: ReadinessReport = {
  status: "not_ready",
  checks: {
    sqlite: { status: "ok" },
    checkpoint: { status: "missing" },
  },
};

const log: AuditLog = {
  id: 1,
  tenant_id: "tenant-1",
  actor_user_id: "user-1",
  action: "http.post",
  resource_type: "",
  resource_id: "",
  metadata: { path: "/api/novels" },
  ip_address: "127.0.0.1",
  user_agent: "test",
  created_at: "2026-08-18T10:00:00+08:00",
};

const summary: MonitoringSummary = {
  run_jobs: { completed: 2, failed: 1 },
  transfer_jobs: { completed: 3 },
  model_calls: { total: 8, failed: 1, duration_ms: 2300, input_tokens: 100, output_tokens: 80 },
};

afterEach(cleanup);

describe("MonitoringDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getReadiness.mockResolvedValue(readiness);
    api.listAuditLogs.mockResolvedValue({ logs: [log] });
    api.getMonitoringSummary.mockResolvedValue(summary);
  });

  it("renders as a modal and presents readiness, totals, and readable audit entries", async () => {
    const { container } = render(<MonitoringDialog open onClose={vi.fn()} />);

    expect(container.querySelector(".model-settings-backdrop")).toContainElement(screen.getByRole("dialog"));
    expect(await screen.findByText("未就绪")).toBeInTheDocument();
    expect(screen.getByText("运行检查点")).toBeInTheDocument();
    expect(screen.getByText("缺失")).toBeInTheDocument();
    expect(screen.getByText("POST /api/novels")).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll(".monitoring-summary strong"), (element) => element.textContent)).toEqual(["3", "3", "8", "2s"]);
  });

  it("keeps successful sections visible when one request fails and can refresh", async () => {
    const user = userEvent.setup();
    api.getMonitoringSummary.mockRejectedValueOnce(new Error("统计服务不可用"));
    render(<MonitoringDialog open onClose={vi.fn()} />);

    expect(await screen.findByText("POST /api/novels")).toBeInTheDocument();
    expect(screen.getByText(/运行聚合：统计服务不可用/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "刷新运行状态" }));
    await waitFor(() => expect(api.getMonitoringSummary).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText(/统计服务不可用/)).not.toBeInTheDocument());
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<MonitoringDialog open onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
