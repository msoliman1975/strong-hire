/** v2 Part 1 (S16): Plan usage (AD-3) and the auto-profile queue (AP-3) against the mock API. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw/http";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { API, mockSignIn } from "../mocks/handlers";
import { mockStore, server } from "../mocks/node";

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
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

describe("Plan usage (AD-3)", () => {
  it("AD-3: shows the tone and difficulty mix by week, newest first", async () => {
    renderAt("/plan-usage");
    expect(await screen.findByRole("heading", { name: "Plan usage", level: 1 })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Tone and difficulty by week" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("2026-10-26");
    expect(rows[0]).toHaveTextContent("2 (40%)"); // as_company and direct, of 5
    expect(rows[1]).toHaveTextContent("2026-10-19");
    expect(screen.getByText("9 sessions created.")).toBeInTheDocument();
    expect(screen.getByText("Tone: Direct").nextElementSibling).toHaveTextContent("2 (22%)");
    expect(screen.getByText("Difficulty: Realistic").nextElementSibling).toHaveTextContent("6 (67%)");
    expect(within(screen.getByRole("navigation", { name: "Admin" })).getByRole("link", { name: "Plan usage" })).toHaveAttribute(
      "href",
      "/plan-usage",
    );
  });

  it("AD-3: plan page views show as not measured, with the reason", async () => {
    renderAt("/plan-usage");
    const label = await screen.findByText("Plan page views");
    const tile = label.closest(".kpi")!;
    expect(tile).toHaveTextContent("Not measured");
    expect(tile).toHaveTextContent("No plan page event is recorded yet");
    expect(screen.getByText("Sessions started from the plan page").closest(".kpi")).toHaveTextContent("Not measured");
  });
});

describe("Auto-profiles (AP-3)", () => {
  it("AP-3: lists pending profiles with the summary and sources", async () => {
    renderAt("/content/auto-profiles");
    expect(await screen.findByRole("heading", { name: "Auto-profiles", level: 1 })).toBeInTheDocument();
    const acme = await screen.findByRole("article", { name: "Acme" });
    expect(acme).toHaveTextContent("Acme builds developer tools");
    expect(acme).toHaveTextContent("Two technical rounds");
    expect(within(acme).getByRole("link", { name: "https://acme.example/about" })).toHaveAttribute(
      "href",
      "https://acme.example/about",
    );
    expect(screen.getByRole("article", { name: "Globex" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Initech" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pending (2)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Approved (1)" })).toBeInTheDocument();
  });

  it("AP-3, AA-6: approving needs a reason and leaves the queue", async () => {
    const user = renderAt("/content/auto-profiles");
    const acme = await screen.findByRole("article", { name: "Acme" });
    await user.click(within(acme).getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve Acme" });
    const confirm = within(dialog).getByRole("button", { name: "Approve" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "reads fine");
    await user.click(confirm);
    expect(await screen.findByRole("button", { name: "Pending (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Acme" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approved (2)" }));
    const approved = await screen.findByRole("article", { name: "Acme" });
    expect(approved).toHaveTextContent("Last reviewed by admin@example.com");
    expect(within(approved).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("AP-3: edits the summary with a reason", async () => {
    let sent: { reason?: string; summary?: string } = {};
    server.events.on("request:start", async ({ request }) => {
      if (request.method === "PUT" && request.url.includes("/summary")) sent = await request.clone().json();
    });
    const user = renderAt("/content/auto-profiles");
    const globex = await screen.findByRole("article", { name: "Globex" });
    await user.click(within(globex).getByRole("button", { name: "Edit summary" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Globex" });
    const save = within(dialog).getByRole("button", { name: "Save summary" });
    const field = within(dialog).getByLabelText("Summary");
    await user.clear(field);
    await user.type(field, "Globex sells everything.");
    await user.type(within(dialog).getByLabelText(/Reason/), "tighter wording");
    await user.click(save);
    expect(await within(globex).findByText("Globex sells everything.")).toBeInTheDocument();
    expect(sent).toEqual({ reason: "tighter wording", summary: "Globex sells everything." });
    server.events.removeAllListeners();
  });

  it("AP-3: retiring is a danger action with a reason", async () => {
    const user = renderAt("/content/auto-profiles");
    const acme = await screen.findByRole("article", { name: "Acme" });
    await user.click(within(acme).getByRole("button", { name: "Retire" }));
    const dialog = screen.getByRole("dialog", { name: "Retire Acme" });
    expect(dialog).toHaveTextContent("stops reaching briefs");
    await user.type(within(dialog).getByLabelText(/Reason/), "wrong company");
    await user.click(within(dialog).getByRole("button", { name: "Retire" }));
    expect(await screen.findByRole("button", { name: "Retired (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Acme" })).not.toBeInTheDocument();
  });

  it("AP-3: shows the API error in the dialog", async () => {
    server.use(
      http.post(`${API}/admin/auto-profiles/:id/approve`, () =>
        HttpResponse.json({ detail: "The profile is approved" }, { status: 409 }),
      ),
    );
    const user = renderAt("/content/auto-profiles");
    const acme = await screen.findByRole("article", { name: "Acme" });
    await user.click(within(acme).getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve Acme" });
    await user.type(within(dialog).getByLabelText(/Reason/), "reads fine");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(dialog).findByText(/The profile is approved/)).toBeInTheDocument();
  });
});
