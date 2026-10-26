import { defineConfig } from "astro/config";

// L04 marketing site: static HTML served by Caddy (infra/caddy/Caddyfile).
// SITE_URL is the public origin, used for canonical links and the sitemap.
export default defineConfig({
  site: process.env.SITE_URL ?? "https://www.getstronghire.com",
  output: "static",
  trailingSlash: "never",
  build: {
    format: "file",
    // The site's Content-Security-Policy allows only same-origin styles and scripts.
    inlineStylesheets: "never",
  },
  vite: { build: { assetsInlineLimit: 0 } },
});
