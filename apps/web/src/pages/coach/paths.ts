/** CO-2: the coach session pages. */
export const coachPath = (sessionId: string) => `/coach/${encodeURIComponent(sessionId)}`;

export interface CoachStart {
  /** An existing story to work on; none starts a new story. */
  story?: string;
  /** The skill the story should show (a "missing" row on Home or the plan). */
  skill?: string;
  /** The plan page whose story-fit gap opened the session. */
  job?: string;
  /** A question typed on Home ("Ask your coach"): sent as the first message. */
  ask?: string;
  /** Opened from a mic button: the session page starts listening when voice is available (CO-6). */
  voice?: boolean;
}

/** Opening this starts a coach session and replaces itself with the session page. */
export function newCoachPath(start: CoachStart = {}) {
  const params = new URLSearchParams();
  for (const key of ["story", "skill", "job", "ask"] as const) {
    const value = start[key];
    if (value) params.set(key, value);
  }
  if (start.voice) params.set("voice", "1");
  const query = params.toString();
  return `/coach/new${query ? `?${query}` : ""}`;
}
