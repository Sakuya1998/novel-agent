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
    openai: { label: "OpenAI", base_url: "https://api.openai.com/v1", chat_models: ["gpt-4o"], embedding_models: ["text-embedding-3-small"] },
    anthropic: { label: "Anthropic", base_url: "", chat_models: ["claude-sonnet-4-5"], embedding_models: [] },
    deepseek: { label: "DeepSeek", base_url: "https://api.deepseek.com", chat_models: ["deepseek-chat"], embedding_models: [] },
    qwen: { label: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", chat_models: ["qwen-plus"], embedding_models: ["text-embedding-v3"] },
    openai_compatible: { label: "OpenAI Compatible", base_url: "", chat_models: [], embedding_models: [] },
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
