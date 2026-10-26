import type { APIRoute } from "astro";

// The preview host also sends X-Robots-Tag: noindex from Caddy until the domain switch.
export const GET: APIRoute = ({ site }) =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${new URL("/sitemap.xml", site)}\n`, {
    headers: { "Content-Type": "text/plain" },
  });
