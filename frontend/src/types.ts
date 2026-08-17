export type NovelStatus = "idle" | "running" | "human_review" | "completed" | "error" | "legacy_read_only";

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
}

export interface Novel {
  id: string;
  title: string;
  genre: string;
  inspiration: string;
  style: string;
  total_chapters: number;
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
}

export interface ConsistencyIssue {
  type?: string;
  description?: string;
  severity?: "high" | "medium" | "low" | string;
  suggestion?: string;
  chapter?: number;
}

export interface WorkbenchState {
  novel_id: string;
  status: NovelStatus;
  current_chapter: number;
  current_phase: string;
  chapters_done: number;
  total_chapters: number;
  next: string[];
  current_draft: Draft;
  issues: ConsistencyIssue[];
  persistence_error: string;
}

export type StreamEvent =
  | { type: "node_done"; node: string }
  | ({ type: "interrupt"; node: "human_review"; chapter_number?: number; title?: string; content?: string; issues?: ConsistencyIssue[]; instruction?: string; persistence_error?: string })
  | { type: "end"; chapters_done: number; current_chapter?: number }
  | { type: "error"; message: string };

export const STAGES = [
  { id: "world_builder", label: "世界观", short: "设" },
  { id: "character_designer", label: "角色", short: "角" },
  { id: "plot_planner", label: "大纲", short: "纲" },
  { id: "scene_writer", label: "写作", short: "写" },
  { id: "style_editor", label: "润色", short: "润" },
  { id: "consistency_checker", label: "质检", short: "检" },
  { id: "human_review", label: "审查", short: "审" },
] as const;
