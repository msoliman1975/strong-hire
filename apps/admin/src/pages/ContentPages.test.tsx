/**
 * Content pages (AT-1..AT-5) against the content mocks: companies with the active toggle,
 * profile import errors, the version diff, the publish confirm (AA-7) and request triage.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";

function signInAdmin() {
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
}

function renderAt(path: string) {
  signInAdmin();
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

describe("Content: companies and profiles", { timeout: 20_000 }, () => {
  it("AT-1: lists companies and turns one off after a reason", async () => {
    const user = renderAt("/content/companies");
    expect(await screen.findByRole("heading", { name: "Companies" })).toBeInTheDocument();
    const row = (await screen.findByRole("link", { name: "Example Corp" })).closest("tr")!;
    expect(within(row).getByText("v1")).toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: "Turn off Example Corp" }));
    const dialog = screen.getByRole("dialog", { name: "Turn off Example Corp?" });
    expect(dialog).toHaveTextContent("Example Corp (example-corp)");
    const confirm = within(dialog).getByRole("button", { name: "Turn off" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "profile is stale");
    await user.click(confirm);
    expect(await within(row).findByRole("button", { name: "Turn on Example Corp" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("AT-3: import shows every validation problem from the API", async () => {
    const user = renderAt("/content/companies");
    await user.click(await screen.findByRole("button", { name: "Import a profile" }));
    const form = screen.getByRole("form", { name: "Import a profile" });
    const paste = within(form).getByLabelText("Or paste the JSON");
    fireEvent.change(paste, { target: { value: '{"company_slug": "acme", "company_name": "Acme"}' } });
    await user.type(within(form).getByLabelText(/Reason/), "first draft");
    await user.click(within(form).getByRole("button", { name: "Validate and import" }));

    const alert = await within(form).findByRole("alert");
    expect(alert).toHaveTextContent("does not match the company profile schema");
    expect(within(alert).getByText("persona: Field required")).toBeInTheDocument();
    expect(within(alert).getByText("sources: Field required")).toBeInTheDocument();

    fireEvent.change(paste, { target: { value: "{not json" } });
    await user.click(within(form).getByRole("button", { name: "Validate and import" }));
    expect(await within(form).findByText(/not valid JSON/)).toBeInTheDocument();
  });

  it("AT-3: a valid file for a new company is stored as a Draft", async () => {
    const user = renderAt("/content/companies");
    await user.click(await screen.findByRole("button", { name: "Import a profile" }));
    const form = screen.getByRole("form", { name: "Import a profile" });
    const { mockProfile } = await import("../mocks/contentHandlers");
    const file = new File([JSON.stringify(mockProfile("acme", "Acme", "Calm"))], "acme.json", {
      type: "application/json",
    });
    await user.upload(within(form).getByLabelText("Profile JSON file"), file);
    expect(await within(form).findByText("Company: acme")).toBeInTheDocument();
    await user.click(within(form).getByLabelText("Add the company if it is new (inactive)"));
    await user.type(within(form).getByLabelText(/Reason/), "new research");
    await user.click(within(form).getByRole("button", { name: "Validate and import" }));
    expect(await within(form).findByText(/Stored acme version 1 as Draft/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Acme" })).toBeInTheDocument();
  });

  it("AT-2: diffs two versions side by side and inline, and shows the JSON with sources", async () => {
    const user = renderAt("/content/companies/example-corp");
    expect(await screen.findByRole("heading", { name: "Example Corp" })).toBeInTheDocument();
    const diff = await screen.findByLabelText("Changes from Version 1 to Version 2");
    const row = within(diff).getByText("persona.pace").closest("tr")!;
    expect(within(row).getByText("Moderate")).toBeInTheDocument();
    expect(within(row).getByText("Fast")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Inline" }));
    const line = within(screen.getByLabelText("Changes from Version 1 to Version 2")).getByText("persona.pace").closest("li")!;
    expect(line).toHaveTextContent("~ persona.pace: Moderate → Fast");

    await user.click(screen.getByRole("button", { name: "View v2" }));
    expect(await screen.findByRole("link", { name: "Example Corp careers" })).toBeInTheDocument();
    expect(screen.getByLabelText("Profile JSON of version 2")).toHaveTextContent('"pace": "Fast"');
  });

  it("AT-4, AA-7: publishing asks to confirm with the company and version, then archives the old one", async () => {
    const user = renderAt("/content/companies/example-corp");
    await user.click(await screen.findByRole("button", { name: "Send to review v2" }));
    let dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Reason/), "ready for review");
    await user.click(within(dialog).getByRole("button", { name: "Send to review example-corp v2" }));

    await user.click(await screen.findByRole("button", { name: "Publish v2" }));
    dialog = screen.getByRole("dialog", { name: "Publish: Example Corp version 2?" });
    expect(dialog).toHaveTextContent("Example Corp (example-corp) version 2");
    expect(dialog).toHaveTextContent("Version 1, published now, becomes archived.");
    const confirm = within(dialog).getByRole("button", { name: "Publish example-corp v2" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "sources checked");
    await user.click(confirm);

    expect(await screen.findByRole("button", { name: "Roll back to this v1" })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const v2 = rows.find((r) => within(r).queryByText("v2"))!;
    expect(within(v2).getByText("published")).toBeInTheDocument();
    expect(within(v2).getByText("admin@example.com")).toBeInTheDocument();
  });
});

describe("Content: company requests (AT-5)", { timeout: 20_000 }, () => {
  it("shows grouped requests and saves a triage state with a reason", async () => {
    const user = renderAt("/content/requests");
    const row = (await screen.findByText("acme")).closest("tr")!;
    expect(row).toHaveTextContent("Acme Inc., ACME");
    expect(row).toHaveTextContent("boards.greenhouse.io");
    expect(within(row).getByText("New")).toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: "Triage acme" }));
    const dialog = screen.getByRole("dialog", { name: 'Triage "acme"' });
    await user.selectOptions(within(dialog).getByLabelText("State"), "planned");
    await user.type(within(dialog).getByLabelText("Note"), "Q4");
    await user.type(within(dialog).getByLabelText(/Reason/), "popular ask");
    await user.click(within(dialog).getByRole("button", { name: "Save triage" }));
    expect(await within(row).findByText("Planned")).toBeInTheDocument();
    expect(row).toHaveTextContent("Q4");
  });
});
