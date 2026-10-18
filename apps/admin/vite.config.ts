/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { msw } from "msw/vite";
import { defineConfig, type Plugin } from "vite";

// The API on the host is at http://localhost:8700 (the Docker stack); override for other setups.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8700";

// Serves mockServiceWorker.js in development only; production builds never include it.
const mswWorker: Plugin = { ...msw({ mode: "worker-only" }), apply: "serve" };

export default defineConfig({
  plugins: [react(), mswWorker],
  server: {
    host: true,
    port: 5181,
    strictPort: true,
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
