/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { msw } from "msw/vite";
import { defineConfig, type Plugin } from "vite";

// In Docker the API is at http://api:8000; on the host it is at http://localhost:8700.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8700";

// Serves mockServiceWorker.js in development only; production builds never include it.
const mswWorker: Plugin = { ...msw({ mode: "worker-only" }), apply: "serve" };

export default defineConfig({
  plugins: [react(), mswWorker],
  server: {
    host: true,
    port: 5180,
    strictPort: true,
    // Docker Desktop bind mounts on Windows do not deliver file events, so poll there.
    watch: process.env.VITE_USE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
