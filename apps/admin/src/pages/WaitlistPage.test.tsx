/** L04: the admin Waitlist page against the mock API. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";

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

describe("Waitlist (L04)", () => {
  it("L04: shows the counts, every entry and a CSV download", async () => {
    renderAt("/waitlist");
    expect(await screen.findByRole("heading", { name: "Waitlist" })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Waitlist entries" });
    const ada = within(table).getByText("ada@example.com").closest("tr")!;
    expect(ada).toHaveTextContent("Within 2 weeks");
    expect(ada).toHaveTextContent("Software engineering");
    expect(ada).toHaveTextContent("reddit");
    const bo = within(table).getByText("bo@example.com").closest("tr")!;
    expect(bo).toHaveTextContent("Not booked");
    expect(screen.getByText("Confirmed", { selector: ".kpi__label" }).nextElementSibling).toHaveTextContent("1");
    expect(screen.getByRole("link", { name: "Download CSV" })).toHaveAttribute(
      "href",
      expect.stringMatching(/\/api\/admin\/waitlist\.csv$/),
    );
    expect(screen.getByRole("link", { name: "Waitlist" })).toHaveAttribute("href", "/waitlist");
  });
});
