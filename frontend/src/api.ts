import type {
  ConnectionTestResult,
  ModelProfile,
  ModelProfileWrite,
  ModelRoutes,
  ModelSettings,
  Novel,
  StreamEvent,
  WorkbenchState,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

function responseError(body: unknown, status: number): string {
  if (!body || typeof body !== "object" || !("detail" in body)) return `请求失败 (${status})`;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") return String(item);
      const issue = item as { loc?: unknown; msg?: unknown };
      const location = Array.isArray(issue.loc)
        ? issue.loc.filter((part) => part !== "body").map(String).join(".")
        : "";
      const message = typeof issue.msg === "string" ? issue.msg : "请求参数无效";
      return location ? `${location}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  return `请求失败 (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(responseError(body, response.status));
  }
  return response.json() as Promise<T>;
}

export function listNovels(): Promise<Novel[]> {
  return request<Novel[]>("/api/novels");
}

export function getNovel(id: string): Promise<Novel> {
  return request<Novel>(`/api/novels/${encodeURIComponent(id)}`);
}

export function getNovelState(id: string): Promise<WorkbenchState> {
  return request<WorkbenchState>(`/api/novels/${encodeURIComponent(id)}/state`);
}

export function createNovel(payload: Pick<Novel, "title" | "genre" | "inspiration" | "total_chapters" | "style">): Promise<Novel> {
  return request<Novel>("/api/novels", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteNovel(id: string): Promise<{ deleted: boolean; novel_id: string }> {
  return request<{ deleted: boolean; novel_id: string }>(`/api/novels/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function getModelSettings(): Promise<ModelSettings> {
  return request<ModelSettings>("/api/model-settings");
}

export function createModelProfile(payload: ModelProfileWrite): Promise<ModelProfile> {
  return request<ModelProfile>("/api/model-settings/profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateModelProfile(id: string, payload: ModelProfileWrite): Promise<ModelProfile> {
  return request<ModelProfile>(`/api/model-settings/profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteModelProfile(id: string): Promise<{ deleted: boolean; profile_id: string }> {
  return request<{ deleted: boolean; profile_id: string }>(
    `/api/model-settings/profiles/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

export function saveModelRoutes(payload: ModelRoutes): Promise<ModelRoutes> {
  return request<ModelRoutes>("/api/model-settings/routes", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function testModelProfile(
  id: string,
  kind: "chat" | "embedding",
  modelName: string,
): Promise<ConnectionTestResult> {
  return request<ConnectionTestResult>(`/api/model-settings/profiles/${encodeURIComponent(id)}/test`, {
    method: "POST",
    body: JSON.stringify({ kind, model_name: modelName }),
  });
}

export async function streamNovel(
  id: string,
  action: "run" | "resume",
  feedback: string | undefined,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/novels/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: action === "resume" ? JSON.stringify({ feedback: feedback || "approve" }) : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  if (!response.body) throw new Error("后端没有返回流");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line) as StreamEvent);
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as StreamEvent);
}
