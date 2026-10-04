import createClient from "openapi-fetch";

import type { paths } from "./schema.gen";

/**
 * The browser reaches the API through the web origin: /api/* is proxied to the API service.
 * The URL is absolute because Node's fetch (used by Vitest) rejects relative URLs.
 */
export const API_BASE = `${globalThis.location?.origin ?? "http://localhost:5180"}/api`;

/**
 * Typed client for the endpoints the API already has (generated from openapi.json).
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

/**
 * JSON request helper for endpoints that later workstreams will add to the API (see planned.ts).
 * When an endpoint lands in openapi.json, move its caller to `apiClient`.
 */
export async function request<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  const data: unknown = text ? JSON.parse(text) : undefined;
  if (!resp.ok) {
    const { message, code } = errorMessage(data, resp.status);
    throw new ApiError(resp.status, message, code);
  }
  return data as T;
}
