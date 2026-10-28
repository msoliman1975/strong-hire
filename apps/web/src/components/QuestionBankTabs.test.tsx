/** QB-1, CU-8: with v2 on, the Questions page is the Question bank, with My questions as a tab; v1 keeps its titles. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockStore } from "../mocks/node";
import { setFeatureOverrides } from "../theme/features";

afterEach(() => setFeatureOverrides({}));

function renderAt(path: string, v2: boolean) {
  const email = "ana@example.com";
  mockStore.db.users[email] = {
    id: "u1",
    org_id: "o1",
    email,
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: "Ana Lopez",
    profile_complete: true,
  };
  mockStore.db.auth = { status: "signed_in", email, userEmail: email };
  setFeatureOverrides({ v2_enabled: v2 });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Question bank", () => {
  it("QB-1: v2 titles the Questions page Question bank, with Questions and My questions tabs", async () => {
    renderAt("/questions", true);
    expect(await screen.findByRole("heading", { level: 1, name: "Question bank" })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "Question bank" });
    expect(within(tabs).getByRole("link", { name: "Questions" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "My questions" })).toHaveAttribute("href", "/questions/mine");
  });

  it("CU-8: My questions is a tab of the Question bank in v2", async () => {
    renderAt("/questions/mine", true);
    expect(await screen.findByRole("heading", { level: 1, name: "Question bank" })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "Question bank" });
    expect(within(tabs).getByRole("link", { name: "My questions" })).toHaveAttribute("aria-current", "page");
  });

  it("FL-1: with v2 off the pages keep their v1 titles and no tabs", async () => {
    renderAt("/questions", false);
    expect(await screen.findByRole("heading", { level: 1, name: "Questions" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Question bank" })).toBeNull();
  });
});
