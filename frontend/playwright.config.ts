import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const frontendRoot = import.meta.dirname;
const repositoryRoot = path.resolve(frontendRoot, "..");
const apiUrl = "http://127.0.0.1:8765";
const webUrl = "http://127.0.0.1:4173";
const runtimeProcess = (globalThis as typeof globalThis & {
  process?: { env?: Record<string, string | undefined>; platform?: string };
}).process;
const python = runtimeProcess?.platform === "win32"
  ? path.join(repositoryRoot, ".venv", "Scripts", "python.exe")
  : path.join(repositoryRoot, ".venv", "bin", "python");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(runtimeProcess?.env?.CI),
  retries: runtimeProcess?.env?.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: webUrl,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: `"${python}" -m scripts.e2e_server --root .tmp/e2e-runtime --port 8765`,
      cwd: repositoryRoot,
      url: `${apiUrl}/healthz`,
      reuseExistingServer: !runtimeProcess?.env?.CI,
      timeout: 120_000,
    },
    {
      command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173",
      cwd: frontendRoot,
      env: { VITE_API_PROXY_TARGET: apiUrl },
      url: webUrl,
      reuseExistingServer: !runtimeProcess?.env?.CI,
      timeout: 120_000,
    },
  ],
});
