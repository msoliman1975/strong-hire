import { describe, expect, it } from "vitest";

import { betaRoleFamilies, defaultRolePlayScenario, rolePlayPart, rolePlayScenarioLabel } from "./labels";

describe("customer success role-play (CS-7)", () => {
  it("CS-7, D-6: customer success defaults to the escalation call at every level", () => {
    for (const level of ["new_grad", "mid", "senior", "staff_principal", null] as const) {
      expect(defaultRolePlayScenario(level, "customer_success")).toBe("escalation_call");
    }
  });

  it("CS-7, D-6: other families keep the level default", () => {
    expect(defaultRolePlayScenario("new_grad", "sales")).toBe("cold_call");
    expect(defaultRolePlayScenario("mid", null)).toBe("discovery_call");
    expect(defaultRolePlayScenario("senior")).toBe("demo_objections");
  });

  it("CS-7, D-7: the live room names the candidate's part by call", () => {
    expect(rolePlayPart("escalation_call")).toBe("the customer success manager");
    expect(rolePlayPart("discovery_call")).toBe("the seller");
  });

  it("CS-7, D-10: the escalation call is a listed call and customer success is Beta", () => {
    expect(rolePlayScenarioLabel.escalation_call).toBe("Escalation call");
    expect(betaRoleFamilies.has("customer_success")).toBe(true);
  });
});
