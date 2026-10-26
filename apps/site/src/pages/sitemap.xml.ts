import type { APIRoute } from "astro";

import { loadGuides } from "../data/guides";

const PAGES = [
  "/",
  "/how-it-works",
  "/sample-debrief",
  "/pricing",
  "/legal/terms",
  "/legal/privacy",
  "/legal/refunds",
  "/legal/privacy-officer",
];

export const GET: APIRoute = ({ site }) => {
  const paths = [...PAGES, ...loadGuides().map((g) => `/guides/${g.slug}/${g.role}`)];
  const urls = paths.map((p) => `  <url><loc>${new URL(p, site)}</loc></url>`).join("\n");
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
    { headers: { "Content-Type": "application/xml" } },
  );
};
