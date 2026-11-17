import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Django target for the /api and /apply proxy. The parity harness sets DJANGO_URL when Django runs on another port.
const DJANGO_URL = process.env.DJANGO_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: DJANGO_URL, changeOrigin: false },
      "/apply": { target: DJANGO_URL, changeOrigin: false },
    },
  },
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: "app",
          environment: "jsdom",
          exclude: ["legacy-specs/**", "node_modules/**", "dist/**", "e2e/**"],
        },
      },
      {
        test: {
          name: "legacy",
          environment: "node",
          include: ["legacy-specs/**/*.test.ts"],
        },
      },
    ],
  },
});
