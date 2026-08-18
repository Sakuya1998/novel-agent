import type {
  ConnectionTestResult,
  AuthSession,
  AuthUser,
  AuditLog,
  CanonDetail,
  CanonOperation,
  ConflictExplanation,
  BookAuditRecord,
  ChapterCandidate,
  ChapterEvaluation,
  CreativeBrief,
  CreativeBriefVersion,
  EvaluationComparison,
  EvaluationBenchmarkRun,
  ModelProfile,
  ModelProfileWrite,
  ModelRoutes,
  ModelSettings,
  ModelTrace,
  MemoryQualityHistory,
  MemoryQualityRun,
  Novel,
  PlanningReviewSubmission,
  PlanningArtifactType,
  PlanningVersion,
  ReviewSubmission,
  RunJob,
  RunJobEventsResponse,
  StreamEvent,
  TransferJob,
  WorkbenchState,
  ReadinessReport,
  MonitoringSummary,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const AUTH_TOKEN_KEY = "novel_agent_access_token";
const AUTH_USER_KEY = "novel_agent_auth_user";

export function getStoredAuthUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(AUTH_USER_KEY);
    return value ? JSON.parse(value) as AuthUser : null;
  } catch {
    return null;
  }
}

function storedAuthToken(): string {
  return typeof window === "undefined" ? "" : window.localStorage.getItem(AUTH_TOKEN_KEY) ?? "";
}

function storeAuthSession(session: AuthSession): AuthSession {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(AUTH_TOKEN_KEY, session.access_token);
    window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(session.user));
  }
  return session;
}

export function clearStoredAuth(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_USER_KEY);
}

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
  const token = storedAuthToken();
  const multipart = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(multipart ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(responseError(body, response.status));
  }
  return response.json() as Promise<T>;
}

export async function exportNovel(
  id: string,
  format: string,
  password = "",
  metadata: { author?: string; publisher?: string; language?: string } = {},
): Promise<{ blob: Blob; filename: string }> {
  const token = storedAuthToken();
  const query = new URLSearchParams({ format });
  if (metadata.author) query.set("author", metadata.author);
  if (metadata.publisher) query.set("publisher", metadata.publisher);
  if (metadata.language) query.set("language", metadata.language);
  const response = await fetch(`${API_BASE}/api/novels/${encodeURIComponent(id)}/export?${query.toString()}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(password ? { "X-Backup-Password": password } : {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(responseError(body, response.status));
  }
  if (response.status === 202) {
    const payload = await response.json() as { job: TransferJob };
    const completed = await waitForTransfer(payload.job.id);
    const download = await fetch(`${API_BASE}/api/transfers/${encodeURIComponent(completed.id)}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!download.ok) {
      const body = await download.json().catch(() => ({}));
      throw new Error(responseError(body, download.status));
    }
    const disposition = download.headers.get("Content-Disposition") ?? "";
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    return {
      blob: await download.blob(),
      filename: encoded ? decodeURIComponent(encoded) : String(completed.result.filename ?? `novel.${format}`),
    };
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  return { blob: await response.blob(), filename: encoded ? decodeURIComponent(encoded) : `novel.${format}` };
}

type ImportNovelResult = { novel: Novel; imported_chapters: number; source_format: string };

async function waitForTransfer(jobId: string): Promise<TransferJob> {
  for (;;) {
    const job = await request<TransferJob>(`/api/transfers/${encodeURIComponent(jobId)}`);
    if (job.status === "completed") return job;
    if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      throw new Error(job.error || "后台传输任务未完成");
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, 350));
  }
}

export async function importNovel(file: File, title = "", password = ""): Promise<ImportNovelResult> {
  const form = new FormData();
  form.append("file", file);
  if (password) form.append("password", password);
  const payload = await request<ImportNovelResult | { job: TransferJob }>(
    `/api/novels/import?title=${encodeURIComponent(title)}`,
    { method: "POST", body: form },
  );
  if (!("job" in payload)) return payload;
  const completed = await waitForTransfer(payload.job.id);
  return completed.result as ImportNovelResult;
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

export async function loginAuth(identifier: string, password: string): Promise<AuthSession> {
  const session = await request<AuthSession>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ identifier, password }),
  });
  return storeAuthSession(session);
}

export async function registerAuth(payload: {
  username: string;
  email: string;
  password: string;
  display_name: string;
  tenant_name: string;
}): Promise<AuthSession> {
  const session = await request<AuthSession>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return storeAuthSession(session);
}

export async function logoutAuth(): Promise<void> {
  try {
    await request<{ logged_out: boolean }>("/api/auth/logout", { method: "POST" });
  } finally {
    clearStoredAuth();
  }
}

export function getReadiness(): Promise<ReadinessReport> {
  return request<ReadinessReport>("/readyz");
}

export function listAuditLogs(limit = 50, action = ""): Promise<{ logs: AuditLog[] }> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (action.trim()) query.set("action", action.trim());
  return request<{ logs: AuditLog[] }>(`/api/audit/logs?${query.toString()}`);
}

export function getMonitoringSummary(): Promise<MonitoringSummary> {
  return request<MonitoringSummary>("/api/monitoring/summary");
}

export function listModelTraces(id: string, limit = 100, agent = ""): Promise<ModelTrace[]> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (agent.trim()) query.set("agent", agent.trim());
  return request<ModelTrace[]>(
    `/api/novels/${encodeURIComponent(id)}/traces?${query.toString()}`,
  );
}

export function listCreativeBriefVersions(id: string): Promise<CreativeBriefVersion[]> {
  return request<CreativeBriefVersion[]>(
    `/api/novels/${encodeURIComponent(id)}/creative-brief/versions`,
  );
}

export function updateCreativeBrief(
  id: string,
  creativeBrief: CreativeBrief,
  expectedVersion: number | undefined,
  changeSummary: string,
): Promise<Novel & {
  changed: boolean;
  stale_candidate_count: number;
  requires_revalidation: boolean;
}> {
  return request(`/api/novels/${encodeURIComponent(id)}/creative-brief`, {
    method: "PUT",
    body: JSON.stringify({
      creative_brief: creativeBrief,
      expected_version: expectedVersion,
      change_summary: changeSummary,
    }),
  });
}

export function listBookAudits(id: string): Promise<BookAuditRecord[]> {
  return request<BookAuditRecord[]>(`/api/novels/${encodeURIComponent(id)}/book-audits`);
}

export function getNovelCanon(id: string): Promise<CanonDetail> {
  return request<CanonDetail>(`/api/novels/${encodeURIComponent(id)}/canon`);
}

export function getNovelConflicts(id: string, chapterNumber?: number): Promise<{ chapter_number: number; issues: ConflictExplanation[]; report: string; canon_version: number }> {
  const query = chapterNumber ? `?chapter_number=${encodeURIComponent(String(chapterNumber))}` : "";
  return request(`/api/novels/${encodeURIComponent(id)}/conflicts${query}`);
}

export function getMemoryQuality(id: string, limit = 20): Promise<MemoryQualityHistory> {
  return request<MemoryQualityHistory>(`/api/novels/${encodeURIComponent(id)}/memory/quality?limit=${limit}`);
}

export function evaluateMemoryQuality(id: string, k = 5): Promise<MemoryQualityRun> {
  return request<MemoryQualityRun>(`/api/novels/${encodeURIComponent(id)}/memory/evaluate`, {
    method: "POST",
    body: JSON.stringify({ k }),
  });
}

export function rebuildMemory(id: string, evaluate = true, k = 5): Promise<{ run: MemoryQualityRun; rebuild: Record<string, unknown>; quality: MemoryQualityRun["report"]; memory: Record<string, unknown> }> {
  return request(`/api/novels/${encodeURIComponent(id)}/memory/rebuild`, {
    method: "POST",
    body: JSON.stringify({ evaluate, k }),
  });
}

export function getChapterVersionDiff(
  id: string,
  chapterNumber: number,
  fromVersion: number,
  toVersion: number,
): Promise<{ from_version: number; to_version: number; diff: string }> {
  const query = new URLSearchParams({
    from_version: String(fromVersion),
    to_version: String(toVersion),
  });
  return request(`/api/novels/${encodeURIComponent(id)}/chapters/${chapterNumber}/versions/diff?${query}`);
}

export function getPlanningVersion(
  id: string,
  artifactType: PlanningArtifactType,
  chapterNumber: number,
  versionNumber: number,
): Promise<PlanningVersion> {
  const query = new URLSearchParams({ chapter_number: String(chapterNumber) });
  return request(`/api/novels/${encodeURIComponent(id)}/planning/${artifactType}/versions/${versionNumber}?${query}`);
}

export function getPlanningVersionDiff(
  id: string,
  artifactType: PlanningArtifactType,
  chapterNumber: number,
  fromVersion: number,
  toVersion: number,
): Promise<{ from_version: number; to_version: number; diff: string }> {
  const query = new URLSearchParams({
    chapter_number: String(chapterNumber),
    from_version: String(fromVersion),
    to_version: String(toVersion),
  });
  return request(`/api/novels/${encodeURIComponent(id)}/planning/${artifactType}/versions/diff?${query}`);
}

export function evaluateChapterVersion(
  id: string,
  chapterNumber: number,
  versionNumber: number,
  includeJudge: boolean,
): Promise<ChapterEvaluation> {
  return request(`/api/novels/${encodeURIComponent(id)}/chapters/${chapterNumber}/versions/${versionNumber}/evaluations`, {
    method: "POST",
    body: JSON.stringify({ include_judge: includeJudge }),
  });
}

export function setChapterEvaluationBaseline(
  id: string,
  chapterNumber: number,
  evaluationId: number,
): Promise<ChapterEvaluation> {
  return request(`/api/novels/${encodeURIComponent(id)}/chapters/${chapterNumber}/evaluations/${evaluationId}/baseline`, {
    method: "PUT",
  });
}

export function compareChapterEvaluations(
  id: string,
  chapterNumber: number,
  fromVersion: number,
  toVersion: number,
): Promise<EvaluationComparison> {
  const query = new URLSearchParams({ from_version: String(fromVersion), to_version: String(toVersion) });
  return request(`/api/novels/${encodeURIComponent(id)}/chapters/${chapterNumber}/evaluations/compare?${query}`);
}

export function listEvaluationBenchmarks(limit = 50): Promise<EvaluationBenchmarkRun[]> {
  return request<EvaluationBenchmarkRun[]>(`/api/evaluations/benchmarks?limit=${limit}`);
}

export function runEvaluationBenchmark(
  includeJudge: boolean,
  baselineRunId = "",
): Promise<EvaluationBenchmarkRun> {
  return request<EvaluationBenchmarkRun>("/api/evaluations/benchmarks", {
    method: "POST",
    body: JSON.stringify({
      include_judge: includeJudge,
      baseline_run_id: baselineRunId || null,
    }),
  });
}

export type CreateNovelPayload = Pick<Novel, "title" | "genre" | "inspiration" | "total_chapters" | "style" | "planning_review_enabled"> & {
  creative_brief: CreativeBrief;
};

export function createNovel(payload: CreateNovelPayload): Promise<Novel> {
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
  review: ReviewSubmission | PlanningReviewSubmission | undefined,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  return streamRequest(`/api/novels/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: action === "resume" ? JSON.stringify(review ?? { feedback: "approve" }) : undefined,
  }, onEvent);
}

export function startNovelJob(
  id: string,
  action: "run" | "resume",
  review?: ReviewSubmission | PlanningReviewSubmission,
): Promise<RunJob> {
  return request(`/api/novels/${encodeURIComponent(id)}/jobs/${action}`, {
    method: "POST",
    body: action === "resume" ? JSON.stringify(review ?? { feedback: "approve" }) : undefined,
  });
}

export function startCanonJob(id: string, operation: CanonOperation): Promise<RunJob> {
  return request(`/api/novels/${encodeURIComponent(id)}/jobs/canon`, {
    method: "POST",
    body: JSON.stringify(operation),
  });
}

export function startBookRevisionJob(
  id: string,
  chapterNumber: number,
  feedback: string,
): Promise<RunJob> {
  return request(`/api/novels/${encodeURIComponent(id)}/jobs/book-revision`, {
    method: "POST",
    body: JSON.stringify({ chapter_number: chapterNumber, feedback }),
  });
}

export function listChapterCandidates(
  id: string,
  chapterNumber: number,
): Promise<ChapterCandidate[]> {
  return request(
    `/api/novels/${encodeURIComponent(id)}/chapters/${chapterNumber}/candidates`,
  );
}

export function startCandidateGenerationJob(
  id: string,
  count: number,
  instruction: string,
): Promise<RunJob> {
  return request(`/api/novels/${encodeURIComponent(id)}/jobs/candidates`, {
    method: "POST",
    body: JSON.stringify({ count, instruction }),
  });
}

export function getRunJobEvents(
  jobId: string,
  afterSequence = 0,
  signal?: AbortSignal,
): Promise<RunJobEventsResponse> {
  const query = new URLSearchParams({ after_sequence: String(afterSequence) });
  return request(`/api/jobs/${encodeURIComponent(jobId)}/events?${query}`, { signal });
}

export function cancelRunJob(jobId: string): Promise<RunJob> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export async function streamCanonUpdate(
  id: string,
  operation: CanonOperation,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  return streamRequest(`/api/novels/${encodeURIComponent(id)}/canon`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(operation),
  }, onEvent);
}

async function streamRequest(
  path: string,
  init: RequestInit,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(responseError(body, response.status));
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
