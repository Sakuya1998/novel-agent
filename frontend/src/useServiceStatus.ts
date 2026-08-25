import { useEffect, useState } from "react";
import { getReadiness } from "./api";

export type ServiceStatus = "checking" | "ready" | "degraded" | "offline";

export function useServiceStatus(refreshInterval = 30_000): ServiceStatus {
  const [status, setStatus] = useState<ServiceStatus>("checking");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function check() {
      try {
        const report = await getReadiness();
        if (active) setStatus(report.status === "ready" ? "ready" : "degraded");
      } catch {
        if (active) setStatus("offline");
      } finally {
        if (active) timer = window.setTimeout(() => void check(), refreshInterval);
      }
    }

    void check();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [refreshInterval]);

  return status;
}
