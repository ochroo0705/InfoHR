import { defineConfig } from "@playwright/test";

// Parity harness: Django page (DJANGO_URL) against its React port (WEB_URL).
// Start both servers first; this config does not start them.
// Defaults match the Django runserver and the Vite dev server ports.
const WEB_URL = process.env.WEB_URL ?? "http://127.0.0.1:5173";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: WEB_URL,
    // COWORK trap: the browser pane reports reduced motion, so force it off here.
    reducedMotion: "no-preference",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
