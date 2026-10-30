/** U05: the first-run routes (ux-spec section 6.1). */
export const START = "/start";
export const readingPath = (resumeId: string, taskId?: string | null) =>
  `/start/reading/${resumeId}${taskId ? `?task=${encodeURIComponent(taskId)}` : ""}`;
export const readyPath = (resumeId: string) => `/start/ready/${resumeId}`;
export const breakdownPath = (resumeId: string) => `/start/check/${resumeId}`;
export const PLAN_STYLE = "/start/plan-style";
export const WHAT_FIRST = "/start/what-first";

/** Which of the three steps (Profile · Your resume · Plan style) a first-run path belongs to. */
export function startStep(pathname: string): 1 | 2 | 3 | null {
  if (pathname === "/welcome") return 1;
  if (pathname === PLAN_STYLE) return 3;
  if (pathname === WHAT_FIRST) return null;
  if (pathname === START || pathname.startsWith(`${START}/`)) return 2;
  return null;
}

export const isStartPath = (pathname: string) => pathname === START || pathname.startsWith(`${START}/`);
