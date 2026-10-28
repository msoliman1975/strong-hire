import { ONBOARDING_STEPS } from "../../components/ui";
import { useFeature } from "../../theme/features";

/** v2 (canvas board R3 Interviews): the add flow's step bar names what the user brings and gets. */
export const V2_ONBOARDING_STEPS = ["Job description", "Your resume", "Your plan"];

export function useOnboardingSteps(): string[] {
  return useFeature("v2_enabled") ? V2_ONBOARDING_STEPS : ONBOARDING_STEPS;
}
