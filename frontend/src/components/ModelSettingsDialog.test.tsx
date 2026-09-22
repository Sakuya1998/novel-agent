import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSettingsDialog } from "./ModelSettingsDialog";

const hookMocks = vi.hoisted(() => ({
  saveProfile: vi.fn(),
  removeProfile: vi.fn(),
  saveRoutes: vi.fn(),
  testProfile: vi.fn(),
  reload: vi.fn(),
}));

const configuredSettings = {
  source: "database" as const,
  templates: {
    openai: { label: "OpenAI", group: "国际服务", protocol: "openai" as const, base_url: "https://api.openai.com/v1", base_url_mode: "fixed" as const, api_key_required: true, supports_embeddings: true, chat_models: ["gpt-4o"], embedding_models: ["text-embedding-3-small"] },
    anthropic: { label: "Anthropic", group: "国际服务", protocol: "anthropic" as const, base_url: "", base_url_mode: "hidden" as const, api_key_required: true, supports_embeddings: false, chat_models: ["claude-sonnet-4-5"], embedding_models: [] },
    gemini: { label: "Google Gemini", group: "国际服务", protocol: "openai" as const, base_url: "https://generativelanguage.googleapis.com/v1beta/openai", base_url_mode: "required" as const, api_key_required: true, supports_embeddings: false, chat_models: ["gemini-3.7-flash"], embedding_models: [] },
    deepseek: { label: "DeepSeek", group: "国内服务", protocol: "openai" as const, base_url: "https://api.deepseek.com", base_url_mode: "required" as const, api_key_required: true, supports_embeddings: false, chat_models: ["deepseek-chat"], embedding_models: [] },
    qwen: { label: "通义千问", group: "国内服务", protocol: "openai" as const, base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", base_url_mode: "required" as const, api_key_required: true, supports_embeddings: true, chat_models: ["qwen-plus"], embedding_models: ["text-embedding-v3"] },
    ollama: { label: "Ollama", group: "本地服务", protocol: "openai" as const, base_url: "http://localhost:11434/v1", base_url_mode: "required" as const, api_key_required: false, supports_embeddings: true, chat_models: ["qwen3:8b"], embedding_models: ["nomic-embed-text"] },
    openai_compatible: { label: "OpenAI Compatible", group: "自定义服务", protocol: "openai" as const, base_url: "", base_url_mode: "required" as const, api_key_required: false, supports_embeddings: true, chat_models: [], embedding_models: [] },
  },
  profiles: [{
    id: "profile_1",
    name: "OpenAI",
    provider: "openai" as const,
    base_url: "https://api.openai.com/v1",
    has_api_key: true,
    api_key_masked: "sk-...test",
    chat_models: ["gpt-4o"],
    embedding_models: ["text-embedding-3-small"],
  }],
  routes: {
    creative: { profile_id: "profile_1", model_name: "gpt-4o" },
    analysis: { profile_id: "profile_1", model_name: "gpt-4o" },
    embedding: { profile_id: "profile_1", model_name: "text-embedding-3-small" },
  },
};

vi.mock("../useModelSettings", () => ({
  useModelSettings: () => ({
    settings: configuredSettings,
    isLoading: false,
    busyAction: "",
    error: "",
    notice: "",
    ...hookMocks,
  }),
}));

describe("ModelSettingsDialog", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("keeps an existing API key out of the editable input and update payload", async () => {
    const user = userEvent.setup();
    render(<ModelSettingsDialog open isStreaming={false} onClose={() => undefined} />);

    expect(screen.getByText("已配置 · sk-...test")).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "保存服务" }));

    expect(hookMocks.saveProfile).toHaveBeenCalledWith(
      expect.objectContaining({ api_key: "", clear_api_key: false }),
      "profile_1",
    );
  });

  it("clears a replacement key after the profile save succeeds", async () => {
    const user = userEvent.setup();
    hookMocks.saveProfile.mockResolvedValueOnce(configuredSettings.profiles[0]);
    render(<ModelSettingsDialog open isStreaming={false} onClose={() => undefined} />);

    await user.type(screen.getByLabelText("API Key"), "replacement-secret");
    await user.click(screen.getByRole("button", { name: "保存服务" }));

    expect(screen.getByLabelText("API Key")).toHaveValue("");
  });

  it("applies the new provider template while editing an existing profile", async () => {
    const user = userEvent.setup();
    hookMocks.saveProfile.mockResolvedValueOnce(configuredSettings.profiles[0]);
    render(<ModelSettingsDialog open isStreaming={false} onClose={() => undefined} />);

    await user.selectOptions(screen.getByLabelText("供应商"), "qwen");
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://dashscope.aliyuncs.com/compatible-mode/v1");
    expect(screen.getByLabelText("聊天模型（每行一个）")).toHaveValue("qwen-plus");
    expect(screen.getByLabelText("嵌入模型（每行一个）")).toHaveValue("text-embedding-v3");

    await user.selectOptions(screen.getByLabelText("供应商"), "anthropic");
    expect(screen.getByLabelText("API 地址")).toBeDisabled();
    expect(screen.getByLabelText("API 地址")).toHaveValue("");
    expect(screen.getByLabelText("聊天模型（每行一个）")).toHaveValue("claude-sonnet-4-5");
    expect(screen.getByLabelText("嵌入模型（每行一个）")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "保存服务" }));

    expect(hookMocks.saveProfile).toHaveBeenCalledWith(expect.objectContaining({
      provider: "anthropic",
      base_url: "",
      api_key: "",
      clear_api_key: false,
      chat_models: ["claude-sonnet-4-5"],
      embedding_models: [],
    }), "profile_1");
  });

  it("offers expanded providers and configures a local Ollama service", async () => {
    const user = userEvent.setup();
    render(<ModelSettingsDialog open isStreaming={false} onClose={() => undefined} />);

    expect(screen.getByRole("option", { name: "Google Gemini" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Ollama" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "新增模型服务" }));
    await user.selectOptions(screen.getByLabelText("供应商"), "ollama");

    expect(screen.getByLabelText("API 地址")).toBeEnabled();
    expect(screen.getByLabelText("API 地址")).toHaveValue("http://localhost:11434/v1");
    expect(screen.getByText("此服务允许无密钥连接")).toBeInTheDocument();
    expect(screen.getByLabelText("聊天模型（每行一个）")).toHaveValue("qwen3:8b");
    expect(screen.getByLabelText("嵌入模型（每行一个）")).toHaveValue("nomic-embed-text");
  });

  it("opens a blank editor when adding a model service", async () => {
    const user = userEvent.setup();
    render(<ModelSettingsDialog open isStreaming={false} onClose={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "新增模型服务" }));

    expect(screen.getByRole("heading", { name: "新增模型服务" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除模型服务" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("服务名称")).toHaveValue("");
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://api.openai.com/v1");
    expect(screen.getByLabelText("API Key")).toHaveAttribute("placeholder", "输入 API Key");
  });

  it("disables profile and route mutations while a novel is running", async () => {
    const user = userEvent.setup();
    render(<ModelSettingsDialog open isStreaming onClose={() => undefined} />);

    expect(screen.getByRole("button", { name: "保存服务" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "测试聊天模型" })).toBeDisabled();
    await user.click(screen.getByRole("tab", { name: "模型分工" }));
    expect(screen.getByRole("button", { name: "保存模型分工" })).toBeDisabled();
  });

  it("handles a rejected profile deletion without leaking an unhandled promise", async () => {
    const user = userEvent.setup();
    hookMocks.removeProfile.mockRejectedValueOnce(new Error("模型服务正在被模型分工使用"));
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    render(<ModelSettingsDialog open isStreaming={false} onClose={() => undefined} />);

    await user.click(screen.getByRole("button", { name: "删除模型服务" }));
    await Promise.resolve();

    expect(hookMocks.removeProfile).toHaveBeenCalledWith("profile_1");
    expect(screen.getByRole("heading", { name: "编辑模型服务" })).toBeInTheDocument();
  });
});
