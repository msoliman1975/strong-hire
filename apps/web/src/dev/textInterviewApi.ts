/**
 * Dev only: the real sessions API (P7) for the text-interview page.
 *
 * The browser mocks (MSW, "planned" mode) still answer POST /sessions and GET /sessions/{id} for
 * the mocked voice flow (#24). This client sends its requests past them with msw's `bypass`, so
 * they reach the API. In tests (Vitest), the test's own MSW handlers must answer instead.
 * This module is imported only by the dev page, which production builds do not include.
 */
import { bypass } from "msw";
import createClient from "openapi-fetch";

import { API_BASE, unwrap } from "../api/client";
import type { paths } from "../api/schema.gen";
import type { components } from "../api/schema.gen";

type S = components["schemas"];
export type SessionRecord = S["SessionRecord"];
export type TextTurns = S["TextTurns"];
export type SessionConfig = S["SessionConfig"];
export type CoachCommand = S["CoachRequest"]["command"];
export type Debrief = S["Debrief"];

const client = createClient<paths>({
  baseUrl: API_BASE,
  credentials: "same-origin",
  fetch: (input: Request) =>
    globalThis.fetch(import.meta.env.MODE === "test" ? input : bypass(input)),
});

export const textInterviewApi = {
  create: async (job_target_id: string, config: SessionConfig) =>
    unwrap(await client.POST("/sessions", { body: { job_target_id, config, channel: "text" } })),
  get: async (session_id: string) =>
    unwrap(await client.GET("/sessions/{session_id}", { params: { path: { session_id } } })),
  open: async (session_id: string) =>
    unwrap(await client.POST("/sessions/{session_id}/text/open", { params: { path: { session_id } } })),
  turn: async (session_id: string, text: string) =>
    unwrap(
      await client.POST("/sessions/{session_id}/text/turn", {
        params: { path: { session_id } },
        body: { text },
      }),
    ),
  coach: async (session_id: string, command: CoachCommand) =>
    unwrap(
      await client.POST("/sessions/{session_id}/coach", {
        params: { path: { session_id } },
        body: { command },
      }),
    ),
  end: async (session_id: string) =>
    unwrap(await client.POST("/sessions/{session_id}/end", { params: { path: { session_id } } })),
  debrief: async (session_id: string) =>
    unwrap(
      await client.GET("/sessions/{session_id}/debrief", { params: { path: { session_id } } }),
    ),
};
