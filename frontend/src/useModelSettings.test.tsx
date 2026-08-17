import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useModelSettings } from "./useModelSettings";

const apiMocks = vi.hoisted(() => ({
  getModelSettings: vi.fn(),
  createModelProfile: vi.fn(),
  updateModelProfile: vi.fn(),
  deleteModelProfile: vi.fn(),
  saveModelRoutes: vi.fn(),
  testModelProfile: vi.fn(),
}));

vi.mock("./api", () => apiMocks);

const emptySettings = {
  source: "unconfigured" as const,
  templates: {
    openai: { label: "OpenAI", base_url: "https://api.openai.com/v1", chat_models: ["gpt-4o"], embedding_models: ["text-embedding-3-small"] },
    anthropic: { label: "Anthropic", base_url: "", chat_models: [], embedding_models: [] },
    deepseek: { label: "DeepSeek", base_url: "https://api.deepseek.com", chat_models: [], embedding_models: [] },
    qwen: { label: "通义千问", base_url: "", chat_models: [], embedding_models: [] },
    openai_compatible: { label: "OpenAI Compatible", base_url: "", chat_models: [], embedding_models: [] },
  },
  profiles: [],
  routes: {},
};

const savedProfile = {
  id: "profile_1",
  name: "OpenAI",
  provider: "openai" as const,
  base_url: "https://api.openai.com/v1",
  has_api_key: true,
  api_key_masked: "sk-...test",
  chat_models: ["gpt-4o"],
  embedding_models: ["text-embedding-3-small"],
};

describe("useModelSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads only while the dialog is open", async () => {
    apiMocks.getModelSettings.mockResolvedValue(emptySettings);
    const { rerender } = renderHook(({ open }) => useModelSettings(open), {
      initialProps: { open: false },
    });

    expect(apiMocks.getModelSettings).not.toHaveBeenCalled();
    rerender({ open: true });

    await waitFor(() => expect(apiMocks.getModelSettings).toHaveBeenCalledOnce());
  });

  it("reloads redacted settings after saving a profile", async () => {
    const savedSettings = { ...emptySettings, source: "database" as const, profiles: [savedProfile] };
    apiMocks.getModelSettings.mockResolvedValueOnce(emptySettings).mockResolvedValueOnce(savedSettings);
    apiMocks.createModelProfile.mockResolvedValue(savedProfile);
    const { result } = renderHook(() => useModelSettings(true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(() => result.current.saveProfile({
      name: "OpenAI",
      provider: "openai",
      base_url: "https://api.openai.com/v1",
      api_key: "sk-test",
      clear_api_key: false,
      chat_models: ["gpt-4o"],
      embedding_models: ["text-embedding-3-small"],
    }));

    expect(apiMocks.createModelProfile).toHaveBeenCalledOnce();
    expect(result.current.settings?.profiles[0].has_api_key).toBe(true);
    expect(result.current.notice).toBe("模型服务已保存");
  });

  it("reports a successful write followed by a failed refresh distinctly", async () => {
    apiMocks.getModelSettings
      .mockResolvedValueOnce(emptySettings)
      .mockRejectedValueOnce(new Error("refresh failed"));
    apiMocks.createModelProfile.mockResolvedValue(savedProfile);
    const { result } = renderHook(() => useModelSettings(true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(() => result.current.saveProfile({
      name: "OpenAI",
      provider: "openai",
      base_url: "https://api.openai.com/v1",
      api_key: "sk-test",
      clear_api_key: false,
      chat_models: ["gpt-4o"],
      embedding_models: ["text-embedding-3-small"],
    }));

    expect(result.current.error).toBe("refresh failed");
    expect(result.current.notice).toBe("模型服务已保存，但刷新失败，请重新打开模型设置");
  });
});
