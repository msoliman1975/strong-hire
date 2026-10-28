/**
 * MSW handler for the transcript page (TR-1), with the shape in openapi.json. Every session id
 * answers the same short behavioral transcript.
 */
import { http, HttpResponse } from "msw/http";

import type { Transcript } from "../pages/transcript/api";

const API = "*/api";

export function mockTranscript(sessionId: string): Transcript {
  const turn = (n: number, speaker: "interviewer" | "candidate", phase: "intro" | "core" | "wrap_up", text: string, at: number) => ({
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    speaker,
    phase,
    text,
    start_ms: at,
    end_ms: at + 4000,
  });
  return {
    session_id: sessionId,
    started_at: "2026-10-01T10:00:00Z",
    ended_at: "2026-10-01T10:30:00Z",
    groups: [
      {
        question_ref: null,
        question_text: null,
        phase: "intro",
        turns: [
          turn(1, "interviewer", "intro", "Hi, I'm Sam. Thanks for making the time today.", 0),
          turn(2, "candidate", "intro", "Thanks for having me.", 5000),
        ],
      },
      {
        question_ref: "q1",
        question_text: "Tell me about a time you disagreed with a teammate.",
        phase: "core",
        turns: [
          turn(3, "interviewer", "core", "Tell me about a time you disagreed with a teammate.", 62000),
          turn(4, "candidate", "core", "On the payments migration we disagreed about the cut-over plan...", 68000),
          turn(5, "interviewer", "core", "What did you do next?", 131000),
          turn(6, "candidate", "core", "I wrote up both options with their risks and we picked the staged one.", 134000),
        ],
      },
      {
        question_ref: null,
        question_text: null,
        phase: "wrap_up",
        turns: [turn(7, "interviewer", "wrap_up", "That's all from me. Thanks again.", 1740000)],
      },
    ],
  };
}

export function transcriptHandlers() {
  return [
    http.get(`${API}/sessions/:sessionId/transcript`, ({ params }) =>
      HttpResponse.json(mockTranscript(String(params.sessionId))),
    ),
  ];
}
