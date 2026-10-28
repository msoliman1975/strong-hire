/**
 * MSW handler for the coach room's voice join (CO-6, S32). The API endpoint is planned; until it
 * lands this answers with the "mock:" URL, and useCoachVoice then uses its scripted mock room.
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
