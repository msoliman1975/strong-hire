import { NavLink } from "react-router";

import { useFeature } from "../theme/features";

/**
 * QB-1, CU-8 in v2: the Questions page is the "Question bank", with "My questions" as a tab
 * inside it (canvas board R3 Account). With `v2_enabled` off the pages keep their v1 titles and
 * no tabs. Returns the page title to use.
 */
export function useQuestionBankTitle(v1Title: string): string {
  return useFeature("v2_enabled") ? "Question bank" : v1Title;
}

export function QuestionBankTabs() {
  const v2 = useFeature("v2_enabled");
  if (!v2) return null;
  return (
    <nav className="tabs" aria-label="Question bank">
      <NavLink to="/questions" end>
        Questions
      </NavLink>
      <NavLink to="/questions/mine">My questions</NavLink>
    </nav>
  );
}
