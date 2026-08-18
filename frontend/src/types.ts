export type NovelStatus = "idle" | "running" | "interrupted" | "blueprint_review" | "scene_review" | "human_review" | "completed" | "error" | "legacy_read_only";

export type AgeRating = "all_ages" | "teen" | "mature";
export type PointOfView = "first_person" | "third_limited" | "third_omniscient" | "multiple";
export type NarrativeTense = "past" | "present" | "mixed";
export type NarrativeDistance = "close" | "medium" | "distant";
export type EndingTone = "unspecified" | "hopeful" | "bittersweet" | "tragic" | "open";

export interface CreativeBrief {
  schema_version?: "creative-brief-v1";
  target_audience: string;
  age_rating: AgeRating;
  point_of_view: PointOfView;
  narrative_tense: NarrativeTense;
  narrative_distance: NarrativeDistance;
  ending_tone: EndingTone;
  themes: string[];
  must_include: string[];
  avoid_content: string[];
  intensity: {
    romance: number;
    mystery: number;
    action: number;
    darkness: number;
  };
  notes: string;
}

export interface CreativeBriefVersion {
  id: number;
  novel_id: string;
  version_number: number;
  source: "created" | "manual" | "legacy" | string;
  change_summary: string;
  content_hash: string;
  created_at: string;
  creative_brief: CreativeBrief;
}

export type RunJobStatus = "queued" | "running" | "waiting_review" | "completed" | "failed" | "cancelled" | "interrupted";

export interface RunJob {
  id: string;
  novel_id: string;
  action: "run" | "resume" | string;
  status: RunJobStatus;
  request: Record<string, unknown>;
  current_node: string;
  error: string;
  cancel_requested: boolean;
  lease_owner?: string;
  lease_expires_at?: string;
  heartbeat_at?: string;
  attempt_count?: number;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at: string;
}

export type TransferJobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";

export interface TransferJob {
  id: string;
  tenant_id: string;
  user_id: string;
  kind: "import" | "export";
  novel_id?: string;
  status: TransferJobStatus;
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at: string;
}

export interface AuditLog {
  id: number;
  tenant_id: string;
  actor_user_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  metadata: Record<string, unknown>;
  ip_address: string;
  user_agent: string;
  created_at: string;
}

export interface ReadinessReport {
  status: "ready" | "not_ready";
  checks: Record<string, { status: string; detail?: string }>;
}

export interface MonitoringSummary {
  run_jobs: Record<string, number>;
  transfer_jobs: Record<string, number>;
  model_calls: {
    total: number;
    failed: number;
    duration_ms: number;
    input_tokens: number;
    output_tokens: number;
  };
}

export type ProviderName = "openai" | "anthropic" | "deepseek" | "qwen" | "openai_compatible";
export type RoutePurpose = "creative" | "analysis" | "embedding";

export interface ProviderTemplate {
  label: string;
  base_url: string;
  chat_models: string[];
  embedding_models: string[];
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: ProviderName;
  base_url: string;
  has_api_key: boolean;
  api_key_masked: string;
  chat_models: string[];
  embedding_models: string[];
  created_at?: string;
  updated_at?: string;
}

export interface ModelProfileWrite {
  name: string;
  provider: ProviderName;
  base_url: string;
  api_key: string;
  clear_api_key: boolean;
  chat_models: string[];
  embedding_models: string[];
}

export interface ModelRoute {
  profile_id: string;
  model_name: string;
  fallback_profile_id?: string;
  fallback_model_name?: string;
}

export type ModelRoutes = Record<RoutePurpose, ModelRoute>;

export interface ModelSettings {
  source: "database" | "environment" | "unconfigured";
  templates: Record<ProviderName, ProviderTemplate>;
  profiles: ModelProfile[];
  routes: Partial<ModelRoutes>;
}

export interface ConnectionTestResult {
  ok: boolean;
  latency_ms: number;
  message: string;
}

export interface Chapter {
  id?: number;
  chapter_number: number;
  title: string;
  content: string;
  summary?: string;
  word_count?: number;
  status?: string;
  scene_plan?: ScenePlanItem[];
}

export interface ScenePlanItem {
  scene_number: number;
  goal: string;
  conflict: string;
  turn: string;
  location: string;
  characters: string[];
  emotion: string;
  estimated_words: number;
  entry_hook?: string;
  exit_hook?: string;
  narrative_beats?: Record<string, unknown>[];
}

export interface SceneDraftItem {
  scene_number: number;
  content: string;
}

export interface Novel {
  id: string;
  title: string;
  genre: string;
  inspiration: string;
  style: string;
  total_chapters: number;
  planning_review_enabled?: boolean;
  creative_brief?: CreativeBrief;
  creative_brief_version?: number;
  created_at?: string;
  updated_at?: string;
  chapters?: Chapter[];
}

export interface Draft {
  chapter_number?: number;
  title?: string;
  content?: string;
  summary?: string;
  word_count?: number;
  scene_plan?: ScenePlanItem[];
  scene_drafts?: SceneDraftItem[];
}

export interface ReviewSubmission {
  feedback: string;
  scene_number?: number;
  version_number?: number;
  candidate_id?: string;
}

export interface ChapterCandidate {
  id: string;
  generation_id: string;
  novel_id: string;
  chapter_number: number;
  candidate_number: number;
  source_hash: string;
  instruction: string;
  title: string;
  content: string;
  summary?: string;
  scene_plan: ScenePlanItem[];
  scene_drafts: SceneDraftItem[];
  scores: Record<string, number>;
  overall_score: number;
  evaluation_schema_version: string;
  status: "available" | "selected" | "stale";
  preview: string;
  created_at: string;
  selected_at?: string;
}

export type PlanningReviewSubmission =
  | { review_type: "blueprint_review"; world_bible: string; characters: Record<string, unknown>[]; outline: Record<string, unknown>[] }
  | { review_type: "scene_review"; scene_plan: ScenePlanItem[] };

export type PlanningArtifactType = "blueprint" | "scene";

export interface PlanningVersion {
  id: number;
  novel_id: string;
  artifact_type: PlanningArtifactType;
  chapter_number: number;
  version_number: number;
  source: "generated" | "approved" | string;
  preview?: string;
  payload?: {
    world_bible?: string;
    characters?: Record<string, unknown>[];
    outline?: Record<string, unknown>[];
    scene_plan?: ScenePlanItem[];
  };
  created_at: string;
}

export interface ChapterVersion {
  id: number;
  chapter_number: number;
  version_number: number;
  source: string;
  summary?: string;
  word_count: number;
  preview: string;
  created_at: string;
  scene_plan?: ScenePlanItem[];
  scene_drafts?: SceneDraftItem[];
}

export interface EvaluationFinding {
  dimension: string;
  score?: number | null;
  message: string;
  severity?: string;
  source: string;
}

export interface ChapterEvaluation {
  id: number;
  novel_id: string;
  chapter_number: number;
  version_number: number;
  content_hash: string;
  evaluator_version: string;
  rubric_version: string;
  model_provider: string;
  model_name: string;
  deterministic_scores: Record<string, number>;
  judge_scores: Record<string, number>;
  overall_score: number;
  findings: EvaluationFinding[];
  judge_error: string;
  is_baseline: boolean;
  created_at: string;
}

export interface EvaluationComparison {
  from_evaluation_id: number;
  to_evaluation_id: number;
  from_version: number;
  to_version: number;
  overall_delta: number;
  status: "improved" | "stable" | "regressed";
  regression_threshold: number;
  dimensions: Record<string, { from: number; to: number; delta: number }>;
}

export interface EvaluationBenchmarkCase {
  id: string;
  category: string;
  title: string;
  input_hash: string;
  minimum_score: number;
  deterministic_scores: Record<string, number>;
  judge_scores: Record<string, number>;
  overall_score: number;
  findings: EvaluationFinding[];
  judge_error: string;
  baseline_score: number | null;
  baseline_delta: number | null;
  regression_status: "not_compared" | "stable" | "regressed";
  passed: boolean;
}

export interface EvaluationBenchmarkRun {
  id: string;
  suite_version: string;
  evaluator_version: string;
  rubric_version: string;
  prompt_hash: string;
  input_hash: string;
  include_judge: boolean;
  model_provider: string;
  model_name: string;
  baseline_run_id: string | null;
  gate_threshold: number;
  regression_threshold: number;
  overall_score: number;
  status: "passed" | "failed";
  judge_error: string;
  cases: EvaluationBenchmarkCase[];
  created_at: string;
}

export type AuthRole = "owner" | "editor" | "viewer";

export interface AuthUser {
  id: string;
  tenant_id: string;
  username: string;
  email: string;
  display_name: string;
  role: AuthRole;
  tenant_name: string;
}

export interface AuthSession {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: AuthUser;
}

export interface ConsistencyIssue {
  type?: string;
  description?: string;
  severity?: "high" | "medium" | "low" | string;
  suggestion?: string;
  chapter?: number;
}

export interface ConflictEvidence {
  label: string;
  value: unknown;
  chapter?: number;
  id?: string;
}

export interface ConflictRepairOption {
  id: string;
  label: string;
  kind: "canon_operation" | "revision_feedback" | "planning_operation" | string;
  feedback?: string;
  reason?: string;
  operation?: CanonOperation;
}

export interface ConflictExplanation {
  conflict_id: string;
  type: string;
  title: string;
  severity: "high" | "medium" | "low" | string;
  description: string;
  evidence: ConflictEvidence[];
  conflicting_records: ConflictEvidence[];
  impact: string;
  repair_options: ConflictRepairOption[];
  source?: string;
  chapter?: number;
}

export interface CanonSummary {
  version: number;
  world_facts: number;
  characters: number;
  timeline_entries: number;
  confirmed_facts: number;
  deprecated_facts: number;
  aliases: number;
  audit_entries: number;
  narrative_threads: number;
  open_threads: number;
  resolved_threads: number;
  overdue_threads: number;
}

export type CanonFactStatus = "active" | "deprecated";

export interface CanonWorldFact {
  id: string;
  path: string;
  value: string;
  source?: string;
  status?: CanonFactStatus;
}

export interface CanonFact {
  id: string;
  kind: string;
  subject: string;
  value: string;
  source?: string;
  status?: CanonFactStatus;
}

export interface CanonCharacter {
  name: string;
  role?: string;
  personality?: string;
  relationships?: unknown[];
  speech_pattern?: string;
  behavior?: string;
  arc?: string;
  last_seen_chapter?: number;
  appearances?: number[];
}

export interface CanonAuditEntry {
  id: string;
  action: string;
  target: string;
  before?: unknown;
  after?: unknown;
  reason: string;
  actor: string;
  created_at: string;
}

export type NarrativeThreadStatus = "planned" | "open" | "resolved" | "abandoned";
export type NarrativeBeatAction = "setup" | "develop" | "resolve";

export interface NarrativeBeat {
  id: string;
  chapter: number;
  action: NarrativeBeatAction;
  description: string;
  status?: "planned" | "completed";
  scene_number?: number;
}

export interface NarrativeThread {
  id: string;
  title: string;
  description: string;
  kind: string;
  priority: "major" | "minor";
  status: NarrativeThreadStatus;
  introduced_chapter: number;
  due_chapter?: number | null;
  resolved_chapter?: number | null;
  source?: string;
  beats: NarrativeBeat[];
}

export interface CanonDetail {
  version: number;
  world_facts: CanonWorldFact[];
  characters: Record<string, CanonCharacter>;
  aliases: Record<string, string>;
  timeline: Record<string, unknown>[];
  facts: CanonFact[];
  narrative_threads: NarrativeThread[];
  audit: CanonAuditEntry[];
}

export interface CanonOperation {
  action: "upsert_fact" | "deprecate_fact" | "confirm_fact" | "merge_alias" | "update_character" | "upsert_thread" | "update_thread_status" | "upsert_thread_beat";
  reason: string;
  target_type?: "world_fact" | "fact";
  target_id?: string;
  path?: string;
  subject?: string;
  kind?: string;
  value?: string;
  alias?: string;
  canonical_name?: string;
  name?: string;
  patch?: Record<string, unknown>;
  title?: string;
  description?: string;
  priority?: "major" | "minor";
  status?: NarrativeThreadStatus;
  introduced_chapter?: number;
  due_chapter?: number | null;
  resolved_chapter?: number;
  beat_id?: string;
  chapter?: number;
  beat_action?: NarrativeBeatAction;
  scene_number?: number;
}

export interface ModelUsageAgent {
  agent: string;
  attempts: number;
  successful_calls: number;
  failed_attempts: number;
  total_tokens: number;
  duration_ms: number;
}

export interface ModelUsageSummary {
  attempts: number;
  successful_calls: number;
  failed_attempts: number;
  fallback_attempts: number;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_attempts: number;
  by_agent: ModelUsageAgent[];
}

export interface ModelTrace {
  id: number;
  novel_id: string;
  agent: string;
  purpose: string;
  provider: string;
  model_name: string;
  attempt: number;
  fallback_used: boolean;
  success: boolean;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  usage_estimated: boolean;
  error_type: string;
  call_id: string;
  trace_id: string;
  input_hash: string;
  output_hash: string;
  input_chars: number;
  output_chars: number;
  created_at: string;
}

export interface MemorySummary {
  schema_version: string;
  chapters: number;
  arcs: number;
  quality_status?: string;
  recall_at_k?: number;
  mrr?: number;
}

export interface MemoryQualityReport {
  schema_version?: string;
  status?: string;
  k?: number;
  case_count?: number;
  passed_cases?: number;
  index_record_count?: number;
  index_hash?: string;
  recall_at_k?: number;
  precision_at_k?: number;
  mrr?: number;
  stale_fact_hit_rate?: number;
  canon_vector_conflict_rate?: number;
  category_metrics?: Record<string, { case_count?: number; recall_at_k?: number; precision_at_k?: number; mrr?: number }>;
  cases?: Record<string, unknown>[];
  errors?: string[];
}

export interface MemoryQualityRun {
  id: number;
  novel_id: string;
  tenant_id?: string;
  mode: "evaluate" | "rebuild" | string;
  index_hash: string;
  report: MemoryQualityReport & { rebuild?: Record<string, unknown>; quality?: MemoryQualityReport };
  created_at: string;
}

export interface MemoryQualityHistory {
  latest: MemoryQualityRun | null;
  runs: MemoryQualityRun[];
}

export interface ReplanProposal {
  status: "stable" | "replanned" | "error";
  impact?: "low" | "medium" | "high";
  rationale?: string;
  outline_updates?: Record<string, unknown>[];
  outline?: Record<string, unknown>[];
  replan_version?: string;
}

export interface QualityGateFinding {
  dimension: string;
  score: number;
  message: string;
  source?: string;
}

export interface QualityGateReport {
  schema_version?: string;
  overall_score: number;
  threshold: number;
  passed: boolean;
  status: "passed" | "rewrite" | "escalated" | "blocked_by_consistency";
  scores?: Record<string, number>;
  findings?: QualityGateFinding[];
  critical_failures?: string[];
}

export interface BookAuditFinding {
  dimension?: string;
  score?: number;
  message: string;
  source?: "deterministic" | "model" | string;
}

export interface BookAuditReport {
  schema_version: string;
  rubric_version: string;
  manuscript_hash: string;
  deterministic_scores: Record<string, number>;
  judge_scores: Record<string, number>;
  overall_score: number;
  findings: BookAuditFinding[];
  revision_priorities: string[];
  judge_error?: string;
  storage_error?: string;
  memory_schema_version?: string;
  memory_index_hash?: string;
}

export interface BookAuditRecord {
  id: number;
  novel_id: string;
  manuscript_hash: string;
  schema_version: string;
  rubric_version: string;
  report: BookAuditReport;
  created_at: string;
}

export interface WorkbenchState {
  novel_id: string;
  status: NovelStatus;
  current_chapter: number;
  current_phase: string;
  chapters_done: number;
  total_chapters: number;
  next: string[];
  review_node?: "blueprint_review" | "scene_review" | "human_review" | "";
  planning_review_enabled?: boolean;
  creative_brief?: CreativeBrief;
  creative_brief_version?: number;
  creative_brief_review_required?: boolean;
  creative_brief_versions?: CreativeBriefVersion[];
  world_bible?: string;
  characters?: Record<string, unknown>[];
  outline?: Record<string, unknown>[];
  replan_proposal?: ReplanProposal;
  chapter_plan?: Record<string, unknown>;
  scene_plan?: ScenePlanItem[];
  planning_versions?: PlanningVersion[];
  chapter_candidates: ChapterCandidate[];
  current_draft: Draft;
  issues: ConsistencyIssue[];
  conflicts?: ConflictExplanation[];
  quality_report?: QualityGateReport | null;
  book_audit?: BookAuditReport | null;
  persistence_error: string;
  versions: ChapterVersion[];
  evaluations: ChapterEvaluation[];
  run_job: RunJob | null;
  model_usage: ModelUsageSummary;
  memory: MemorySummary;
  canon: CanonSummary;
}

export type StreamEvent =
  | { type: "job_started"; job_id: string }
  | { type: "node_done"; node: string }
  | ({ type: "interrupt"; node: "human_review"; chapter_number?: number; title?: string; content?: string; scene_plan?: ScenePlanItem[]; issues?: ConsistencyIssue[]; instruction?: string; persistence_error?: string })
  | ({ type: "interrupt"; node: "blueprint_review"; world_bible: string; characters: Record<string, unknown>[]; outline: Record<string, unknown>[]; instruction?: string })
  | ({ type: "interrupt"; node: "scene_review"; chapter_number?: number; chapter_plan?: Record<string, unknown>; scene_plan: ScenePlanItem[]; instruction?: string })
  | { type: "end"; chapters_done: number; current_chapter?: number }
  | { type: "candidate_ready"; candidate_id: string; candidate_number: number; overall_score: number }
  | { type: "candidates_ready"; chapter_number: number; count: number }
  | { type: "error"; message: string }
  | { type: "cancelled" | "interrupted"; message: string };

export interface RunJobEventRecord {
  id: number;
  job_id: string;
  sequence: number;
  event_type: string;
  payload: StreamEvent;
  created_at: string;
}

export interface RunJobEventsResponse {
  job: RunJob;
  events: RunJobEventRecord[];
}

export const STAGES = [
  { id: "world_builder", label: "世界观", short: "设" },
  { id: "character_designer", label: "角色", short: "角" },
  { id: "plot_planner", label: "大纲", short: "纲" },
  { id: "blueprint_review", label: "蓝图审阅", short: "审" },
  { id: "scene_planner", label: "分镜", short: "镜" },
  { id: "scene_review", label: "分镜审阅", short: "审" },
  { id: "scene_writer", label: "写作", short: "写" },
  { id: "scene_rewriter", label: "局部修订", short: "修" },
  { id: "style_editor", label: "润色", short: "润" },
  { id: "consistency_checker", label: "质检", short: "检" },
  { id: "human_review", label: "审查", short: "审" },
  { id: "book_auditor", label: "全书终审", short: "终" },
] as const;
