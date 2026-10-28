/**
 * MSW handler for the coach room's voice join (CO-6), the shape of strong_api.coach's
 * POST /coach/sessions/{id}/voice/join. Only the mocks (VITE_API_MOCKS=all and tests) use it: it
 * answers with the "mock:" URL, so useCoachVoice uses its scripted room instead of LiveKit.
 */
import { http, HttpResponse } from "msw/http";

import { MOCK_VOICE_URL } from "../session/voice";

const API = "*/api";

export function coachVoiceHandlers() {
  return [
    http.post(`${API}/coach/sessions/:sessionId/voice/join`, ({ params }) =>
      HttpResponse.json({
        livekit_url: MOCK_VOICE_URL,
        room: `coach-${String(params.sessionId)}`,
        token: "mock-token",
        identity: "candidate-mock",
      }),
    ),
  ];
}
