import { afterEach, describe, expect, it, vi } from "vitest";
import { createModelProfile, exportNovel, getAuthStatus, getReadiness, loginAuth } from "./api";

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

  it("clears stale browser sessions when authentication is disabled", async () => {
    window.localStorage.setItem("novel_agent_access_token", "stale-token");
    window.localStorage.setItem("novel_agent_auth_user", JSON.stringify({ username: "stale" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      enabled: false,
      user: { id: "user_local", tenant_id: "tenant_local", username: "local" },
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await expect(getAuthStatus()).resolves.toMatchObject({ enabled: false });

    expect(window.localStorage.getItem("novel_agent_access_token")).toBeNull();
    expect(window.localStorage.getItem("novel_agent_auth_user")).toBeNull();
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

  it("returns readiness details when the service reports not ready", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "not_ready",
      checks: { checkpoint: { status: "missing" }, sqlite: { status: "ok" } },
    }), { status: 503, headers: { "Content-Type": "application/json" } })));

    await expect(getReadiness()).resolves.toMatchObject({
      status: "not_ready",
      checks: { checkpoint: { status: "missing" } },
    });
  });

  it("rejects an invalid readiness response instead of showing a false status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Vite fallback</html>", {
      status: 200,
      headers: { "Content-Type": "text/html" },
    })));

    await expect(getReadiness()).rejects.toThrow("就绪检查返回了无效数据");
  });

  it("uses a stable message for network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getAuthStatus()).rejects.toThrow("无法连接后端服务，请检查网络或服务状态");
  });

  it("distinguishes request timeouts from other network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("Timed out", "TimeoutError")));

    await expect(getAuthStatus()).rejects.toThrow("请求超时，请稍后重试");
  });

  it("rejects invalid successful JSON responses with a useful message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not-json", { status: 200 })));

    await expect(getAuthStatus()).rejects.toThrow("后端返回了无法解析的数据");
  });
});
