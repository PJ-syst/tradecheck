import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

process.env.TRADECHECK_TEST_SHUTDOWN = randomUUID();

export default defineConfig({
  testDir: "./tests/browser",
  outputDir: "./data/test-results",
  workers: 1,
  globalTeardown: "./tests/browser/teardown.js",
  use: {
    baseURL: "http://127.0.0.1:8011",
    browserName: "chromium",
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 1100 },
  },
  webServer: {
    command: `python tests/browser_server.py "${join(tmpdir(), `tradecheck-browser-${randomUUID()}.sqlite3`)}"`,
    url: "http://127.0.0.1:8011/api/health",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
