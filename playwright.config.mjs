import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const runtimeDir = "/tmp/hcs-contract-fixes-browser-runtime";
fs.rmSync(runtimeDir, { recursive: true, force: true });
fs.mkdirSync(runtimeDir, { recursive: true });
const localChrome = process.env.PLAYWRIGHT_EXECUTABLE_PATH
  ?? (process.platform === "darwin" ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" : undefined);

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  fullyParallel: false,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    launchOptions: localChrome && fs.existsSync(localChrome) ? { executablePath: localChrome } : undefined,
  },
  webServer: [
    {
      command: `HCS_RUNTIME_DIR=${runtimeDir} PYTHONPATH=apps/api/src uv run --project apps/api python -m uvicorn hcs_api.main:app --host 127.0.0.1 --port 8012`,
      url: "http://127.0.0.1:8012/api/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "VITE_API_BASE=http://127.0.0.1:8012 npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5174",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
