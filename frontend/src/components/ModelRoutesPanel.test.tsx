import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelSettings } from "../types";
import { ModelRoutesPanel } from "./ModelRoutesPanel";

afterEach(cleanup);

describe("ModelRoutesPanel", () => {
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
