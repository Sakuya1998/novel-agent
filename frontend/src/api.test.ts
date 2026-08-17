import { afterEach, describe, expect, it, vi } from "vitest";
import { createModelProfile } from "./api";

describe("model settings API errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("formats Pydantic validation details instead of showing object text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [{ loc: ["body", "base_url"], msg: "Field required", type: "missing" }],
    }), { status: 422, headers: { "Content-Type": "application/json" } })));

    await expect(createModelProfile({
      name: "Custom",
      provider: "openai_compatible",
      base_url: "",
      api_key: "",
      clear_api_key: false,
      chat_models: [],
      embedding_models: [],
    })).rejects.toThrow("base_url: Field required");
  });
});
