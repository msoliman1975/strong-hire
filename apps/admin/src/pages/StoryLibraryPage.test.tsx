/** v2 Part 2 (S25): Story library metrics (AD-4) against the mock API. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";
import { MOCK_PART2_STORIES } from "../mocks/part2Handlers";

function renderAt(path: string) {
  mockStore.db.users["admin@example.com"] = {
    id: "00000000-0000-4000-8000-0000000000a9",
    org_id: "00000000-0000-4000-8000-0000000000b9",
    email: "admin@example.com",
    auth_provider: "dev",
    training_consent: false,
    created_at: "2026-10-01T10:00:00Z",
    full_name: null,
    profile_complete: true,
  };
  mockSignIn(mockStore, "admin@example.com");
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Story library (AD-4)", () => {
  it("AD-4: shows save rate with its target, stories per user and the Draft to Proven rate", async () => {
    renderAt("/story-library");
    expect(await screen.findByRole("heading", { name: "Story library", level: 1 })).toBeInTheDocument();
    const save = (await screen.findByText("Story save rate (30 days)")).closest(".kpi")!;
    expect(save).toHaveTextContent("Target");
    expect(screen.getByText("Stories per user").closest(".kpi")).toBeInTheDocument();
    expect(screen.getByText("Draft to Proven rate").closest(".kpi")).toBeInTheDocument();
    expect(screen.getByText(/Save rate cohort: 3 of 8 users\./)).toBeInTheDocument();
    expect(screen.getByText("Saved from a debrief").nextElementSibling).toHaveTextContent("6");
    expect(within(screen.getByRole("navigation", { name: "Admin" })).getByRole("link", { name: "Story library" })).toHaveAttribute(
      "href",
      "/story-library",
    );
  });

  it("AD-4: delivery metric trends by week, newest first, with a dash for weeks without data", async () => {
    renderAt("/story-library");
    const table = await screen.findByRole("table", { name: "Stories and delivery by week" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("2026-10-26");
    expect(rows[0]).toHaveTextContent("–");
    expect(rows[1]).toHaveTextContent("2026-10-19");
    expect(rows[1]).toHaveTextContent("148");
    expect(rows[1]).toHaveTextContent("3.4");
  });

  it("AD-4: the metrics carry no story text field", () => {
    const keys = JSON.stringify(MOCK_PART2_STORIES);
    for (const field of ["title", "context", "stakes", "action", "result", "reflection", "notes"]) {
      expect(keys).not.toContain(`"${field}"`);
    }
  });
});
