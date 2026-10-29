import { ONBOARDING_STEPS } from "../../components/ui";
import { checkPath } from "../../paths";
import { useFeature } from "../../theme/features";

/** v2 (canvas board R3 Interviews): the add flow's step bar names what the user brings and gets. */
export const V2_ONBOARDING_STEPS = ["Job description", "Your resume", "Your plan"];

export function useOnboardingSteps(): string[] {
  return useFeature("v2_enabled") ? V2_ONBOARDING_STEPS : ONBOARDING_STEPS;
}

/**
 * Where each done step links back to: the job (its confirm page) and the CV picked for it (its
 * check page), or the resume step when no CV is picked yet.
 */
export function onboardingLinks(jobId: string, resumeId?: string | null): (string | null)[] {
  if (!jobId) return [];
  return [`/jobs/${jobId}/confirm`, resumeId ? checkPath(jobId, resumeId) : `/jobs/${jobId}/resume`];
}

/** One line under the step bar: how the user got to this step and what it is for. */
export const STEP_NOTES = {
  job: "Step 1 of 3. Add the job description you are interviewing for. We build your plan from it.",
  confirmJob: "Step 1 of 3. Check what we read from the job description, then pick your CV.",
  resume: "You added the job description. Now pick the CV you sent them, so we can compare the two.",
  check: "You picked this CV for the job. Check what we read, then continue to your plan.",
  context:
    "Your CV is checked. Before we build your plan, add anything you know about this interview. It is optional: skip it if you know nothing yet.",
} as const;
