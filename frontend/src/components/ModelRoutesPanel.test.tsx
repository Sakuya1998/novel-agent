import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelSettings } from "../types";
import { ModelRoutesPanel } from "./ModelRoutesPanel";

afterEach(cleanup);

describe("ModelRoutesPanel", () => {
  it("defaults each route to a profile that actually lists a compatible model", () => {
    const settings: ModelSettings = {
      source: "database",
      templates: {} as ModelSettings["templates"],
      profiles: [
        {
          id: "chat-only",
          name: "Chat only",
          provider: "openai_compatible",
          base_url: "https://chat.example.com/v1",
          has_api_key: true,
          api_key_masked: "***",
          chat_models: ["chat-model"],
          embedding_models: [],
        },
        {
          id: "empty",
          name: "Empty",
          provider: "qwen",
          base_url: "https://empty.example.com/v1",
          has_api_key: true,
          api_key_masked: "***",
          chat_models: [],
          embedding_models: [],
        },
        {
          id: "embedding",
          name: "Embedding",
          provider: "qwen",
          base_url: "https://embed.example.com/v1",
          has_api_key: true,
          api_key_masked: "***",
          chat_models: [],
          embedding_models: ["embed-model"],
        },
      ],
      routes: {},
    };

    render(<ModelRoutesPanel settings={settings} disabled={false} busyAction="" onSave={vi.fn()} />);

    const primaryProfiles = screen.getAllByLabelText("主模型服务");
    const primaryModels = screen.getAllByLabelText("主模型名称");
    expect(primaryProfiles[0]).toHaveValue("chat-only");
    expect(primaryModels[0]).toHaveValue("chat-model");
    expect(primaryProfiles[1]).toHaveValue("chat-only");
    expect(primaryModels[1]).toHaveValue("chat-model");
    expect(primaryProfiles[2]).toHaveValue("embedding");
    expect(primaryModels[2]).toHaveValue("embed-model");
  });

  it("saves an explicit fallback for chat routes", async () => {
    const settings: ModelSettings = {
      source: "database",
      templates: {} as ModelSettings["templates"],
      profiles: [
        {
          id: "primary",
          name: "Primary",
          provider: "openai",
          base_url: "https://api.openai.com/v1",
          has_api_key: true,
          api_key_masked: "***",
          chat_models: ["gpt-4o"],
          embedding_models: ["text-embedding-3-small"],
        },
        {
          id: "fallback",
          name: "Fallback",
          provider: "anthropic",
          base_url: "",
          has_api_key: true,
          api_key_masked: "***",
          chat_models: ["claude-sonnet-4-5"],
          embedding_models: [],
        },
      ],
      routes: {
        creative: { profile_id: "primary", model_name: "gpt-4o" },
        analysis: { profile_id: "primary", model_name: "gpt-4o" },
        embedding: { profile_id: "primary", model_name: "text-embedding-3-small" },
      },
    };
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ModelRoutesPanel settings={settings} disabled={false} busyAction="" onSave={onSave} />);

    await userEvent.selectOptions(screen.getAllByLabelText("备用模型服务")[0], "fallback");
    await userEvent.click(screen.getByRole("button", { name: "保存模型分工" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      creative: expect.objectContaining({
        fallback_profile_id: "fallback",
        fallback_model_name: "claude-sonnet-4-5",
      }),
    }));
  });
});
