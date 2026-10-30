/**
 * U05 first-run routing (ON-1, ON-5): with v2 on, a user with no resume starts at /start, and a
 * user with a resume but no plan style resumes at the plan style screen when they land on Home.
 * Pages that work without a resume (account, help, profile, dev pages) are never redirected.
 */
import { useQuery } from "@tanstack/react-query";

import { accountApi } from "../../api/account";
import { resumesApi } from "../../api/inputs";
import { isStartPath, PLAN_STYLE, START } from "./paths";

let gateOn = true;

/**
 * Tests only: turn the first-run routing off. Most screen tests render one v2 page for a user who
 * has not added a resume; the onboarding tests turn it back on.
 */
export function setFirstRunGate(on: boolean) {
  gateOn = on;
}

const OPEN_PATHS = [/^\/welcome$/, /^\/account(\/|$)/, /^\/help$/, /^\/upgrade$/, /^\/dev\//];

/** Where to send the user instead of `pathname`, or null to stay. Undefined while loading. */
export function useFirstRunRedirect(wanted: boolean, pathname: string): string | null | undefined {
  const enabled = wanted && gateOn;
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: resumesApi.list, enabled });
  const profile = useQuery({ queryKey: ["account", "profile"], queryFn: accountApi.getProfile, enabled });
  if (!enabled || isStartPath(pathname) || OPEN_PATHS.some((p) => p.test(pathname))) return null;
  if (resumes.isError || profile.isError) return null; // never block the app on these reads
  if (!resumes.data || !profile.data) return undefined;
  const hasResume = resumes.data.some((r) => !r.deleted);
  if (!hasResume) return START;
  if (!profile.data.plan_style && pathname === "/") return PLAN_STYLE;
  return null;
}
