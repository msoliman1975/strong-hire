/** RMAP-2: the "Used by" line on the Resumes page names each company once. */
import { describe, expect, it } from "vitest";

import type { RoleOut } from "../../api/types";
import { usedBy } from "./ResumesListPage";

const role = (company: string, resumeId: string) =>
  ({ role: { company_name: company, name: null }, interviews: [{ interview: { resume_id: resumeId } }] }) as unknown as RoleOut;

describe("usedBy", () => {
  it("RMAP-2: a company with two roles is named once, with its count", () => {
    const roles = [role("Rubrik", "a"), role("Rubrik", "a"), role("Sourcegraph", "a"), role("Stripe", "b")];
    expect(usedBy(roles, "a")).toBe("Used by Rubrik (2 roles) and Sourcegraph");
  });

  it("RMAP-2: one company, no role, and roles still loading", () => {
    expect(usedBy([role("Stripe", "b")], "b")).toBe("Used by Stripe");
    expect(usedBy([role("Stripe", "b")], "a")).toBe("Not used by a role");
    expect(usedBy(undefined, "a")).toBeNull();
  });
});
