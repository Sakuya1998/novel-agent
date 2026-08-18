import { afterEach, describe, expect, it, vi } from "vitest";
import { createModelProfile, exportNovel, loginAuth } from "./api";

describe("model settings API errors", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

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

  it("stores a login token and sends it on later requests", async () => {
    window.localStorage.clear();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: "token-1",
        token_type: "bearer",
        expires_at: "2026-09-18T00:00:00Z",
        user: { id: "u1", tenant_id: "t1", username: "alice", email: "", display_name: "Alice", role: "owner", tenant_name: "A" },
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ source: "unconfigured", templates: {}, profiles: [], routes: {} }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await loginAuth("alice", "password-1");
    await createModelProfile({ name: "X", provider: "openai", base_url: "", api_key: "", clear_api_key: false, chat_models: [], embedding_models: [] });

    expect((fetchMock.mock.calls[1][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer token-1" });
  });

  it("polls a background export and downloads the completed file", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ job: { id: "transfer-1" } }), { status: 202, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "transfer-1", status: "completed", result: { filename: "book.zip" }, error: "" }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(new Blob(["PK"]), { status: 200, headers: { "Content-Disposition": "attachment; filename*=UTF-8''book.zip" } }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("setTimeout", (callback: TimerHandler) => { if (typeof callback === "function") callback(); return 0; });

    const result = await exportNovel("novel-1", "backup", "secret");

    expect(result.filename).toBe("book.zip");
    expect(fetchMock.mock.calls[0][0]).toContain("format=backup");
    expect(fetchMock.mock.calls[0][0]).not.toContain("secret");
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).toMatchObject({ "X-Backup-Password": "secret" });
  });
});
