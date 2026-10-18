import createClient from "openapi-fetch";

import type { paths } from "./schema.gen";

/**
 * The browser reaches the API through the admin origin: admin.<domain>/api/* is proxied to the
 * API service (Caddy in production, Vite on port 5181 in development), so the session cookie is
 * the admin host's own. The URL is absolute because Node's fetch (used by Vitest) rejects
 * relative URLs.
 */
export const API_BASE = `${globalThis.location?.origin ?? "http://localhost:5181"}/api`;

/**
 * Typed client generated from the API's OpenAPI document. The admin app reads the same
 * `apps/web/openapi.json` as the web app (`pnpm gen:api`), so there is one copy to keep fresh.
 * `fetch` is looked up on each call, so test tools that patch it later (MSW in Node) still apply.
 */
export const apiClient = createClient<paths>({
  baseUrl: API_BASE,
  credentials: "same-origin",
  fetch: (input: Request) => globalThis.fetch(input),
});

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function errorMessage(body: unknown, status: number): { message: string; code: string | null } {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return { message: detail, code: null };
    if (detail && typeof detail === "object" && "message" in detail) {
      const d = detail as { message: unknown; code?: unknown };
      return { message: String(d.message), code: typeof d.code === "string" ? d.code : null };
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown };
      return { message: String(first.msg ?? "Invalid request"), code: "validation" };
    }
  }
  return { message: `Request failed (HTTP ${status})`, code: null };
}

/** Turns an openapi-fetch result into data, or throws ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const { message, code } = errorMessage(result.error, result.response.status);
    throw new ApiError(result.response.status, message, code);
  }
  return result.data as T;
}
