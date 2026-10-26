// The public marketing site for getstronghire.com (L04). Static HTML, served by Caddy on the apex.
// The app lives on app.getstronghire.com. See README.md.
import { defineConfig } from "astro/config";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

export default defineConfig({
  site: process.env.SITE_URL ?? "https://getstronghire.com",
  trailingSlash: "never",
  build: {
    format: "file",
    // Strict CSP on the apex (style-src 'self'): no inline styles or scripts.
    inlineStylesheets: "never",
  },
  vite: {
    build: { assetsInlineLimit: 0 },
    // Guides read the company profiles from /profiles at build time.
    server: { fs: { allow: [repoRoot] } },
  },
});
