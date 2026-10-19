/**
 * Alerts pages (AL-1, AL-4, AL-6) against the alerts mocks: rules with state badges, the firing
 * count in the nav, enable/mute/test with a reason, the edit form, and the history.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { parseLabels } from "../components/alerts";
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

async function ruleRow(name: string) {
  const link = await screen.findByRole("link", { name }, SLOW);
  const row = link.closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return within(row);
}

// The first render in a cold test worker can take a few seconds.
const SLOW = { timeout: 5_000 };

describe("alerts pages", { timeout: 20_000 }, () => {
  it("AL-4: lists rules with state badges, firing first, and a firing count in the nav", async () => {
    signInAdmin();
    renderAt("/alerts");
    expect(await screen.findByRole("heading", { name: "Alert rules" }, SLOW)).toBeInTheDocument();
    const rows = await screen.findAllByRole("row", undefined, SLOW);
    expect(within(rows[1]).getByText("Firing")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("link", { name: "Disk filling" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Admin" });
    expect(await within(nav).findByLabelText("1 firing", undefined, SLOW)).toBeInTheDocument();
    const disk = await ruleRow("Disk filling");
    expect(disk.getByText(/last\(host\.disk_pct \{mount=pgdata\}\) over 5 min > 85 %/)).toBeInTheDocument();
    expect(disk.getByText("88.40 %")).toBeInTheDocument();
  });

  it("AL-6: sends a test alert after asking for a reason", async () => {
    signInAdmin();
    const user = renderAt("/alerts/rules");
    const row = await ruleRow("API down");
    await user.click(row.getByRole("button", { name: "Test" }));
    const dialog = screen.getByRole("dialog", { name: "Send a test alert for API down?" });
    const send = within(dialog).getByRole("button", { name: "Send test" });
    expect(send).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "check the inbox");
    await user.click(send);
    expect(await screen.findByText("Test alert for API down sent to the alert address.", undefined, SLOW)).toBeInTheDocument();
  });

  it("AL-4: mutes a rule and disables another", async () => {
    signInAdmin();
    const user = renderAt("/alerts/rules");
    let row = await ruleRow("Spend high");
    await user.click(row.getByRole("button", { name: "Mute" }));
    const dialog = screen.getByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Mute for"), "24");
    await user.type(within(dialog).getByLabelText(/Reason/), "known spike");
    await user.click(within(dialog).getByRole("button", { name: "Mute" }));
    expect(await screen.findByText("Spend high is muted for 24 h.", undefined, SLOW)).toBeInTheDocument();
    row = await ruleRow("Spend high");
    expect(await row.findByRole("button", { name: "Unmute" })).toBeInTheDocument();

    const disk = await ruleRow("Disk filling");
    await user.click(disk.getByRole("checkbox", { name: "Enabled: Disk filling" }));
    await user.type(within(screen.getByRole("dialog")).getByLabelText(/Reason/), "moving the volume");
    await user.click(screen.getByRole("button", { name: "Disable" }));
    expect(await screen.findByText("Disk filling is disabled.", undefined, SLOW)).toBeInTheDocument();
    expect(await screen.findByLabelText("Enabled: Disk filling", undefined, SLOW)).not.toBeChecked();
  });

  it("AL-1: adds a rule from the form", async () => {
    signInAdmin();
    const user = renderAt("/alerts/rules/new");
    expect(await screen.findByRole("heading", { name: "New alert rule" }, SLOW)).toBeInTheDocument();
    await user.type(await screen.findByLabelText("Name", undefined, SLOW), "Queue backed up");
    await user.selectOptions(screen.getByLabelText("Metric"), "queue.depth");
    await user.type(screen.getByLabelText("Labels"), "queue=arq:queue");
    await user.selectOptions(screen.getByLabelText("Aggregation"), "avg");
    await user.type(screen.getByLabelText(/Threshold/), "abc");
    await user.click(screen.getByRole("button", { name: "Add rule" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The threshold must be a number.");
    await user.clear(screen.getByLabelText(/Threshold/));
    await user.type(screen.getByLabelText(/Threshold/), "50");
    await user.click(screen.getByRole("button", { name: "Add rule" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Reason/), "watch the queue");
    await user.click(within(dialog).getByRole("button", { name: "Add rule" }));
    expect(await screen.findByRole("heading", { name: "Alert rules" }, SLOW)).toBeInTheDocument();
    const row = await ruleRow("Queue backed up");
    expect(row.getByText(/avg\(queue\.depth \{queue=arq:queue\}\) over 5 min > 50 jobs/)).toBeInTheDocument();
  });

  it("AL-1: a derived metric fixes the aggregation and a default rule keeps its name", async () => {
    signInAdmin();
    const user = renderAt("/alerts/rules/00000000-0000-4000-8000-0000000000e3");
    expect(await screen.findByRole("heading", { name: "Spend high" }, SLOW)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Aggregation")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Delete rule" })).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText(/Threshold/));
    await user.type(screen.getByLabelText(/Threshold/), "70");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await user.type(within(screen.getByRole("dialog")).getByLabelText(/Reason/), "earlier warning");
    await user.click(screen.getByRole("button", { name: "Save" }));
    const row = await ruleRow("Spend high");
    expect(row.getByText(/≥ 70 %/)).toBeInTheDocument();
  });

  it("AL-4: history lists events and filters by kind", async () => {
    signInAdmin();
    const user = renderAt("/alerts/history");
    expect(await screen.findByRole("heading", { name: "Alert history" }, SLOW)).toBeInTheDocument();
    expect(await screen.findByRole("cell", { name: "Fired" }, SLOW)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Resolved" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Kind"), "resolved");
    expect(await screen.findByRole("cell", { name: "API down" }, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "Fired" })).not.toBeInTheDocument();
  });

  it("parses label filters", () => {
    expect(parseLabels("")).toEqual({});
    expect(parseLabels("service=worker|voice, mount=root")).toEqual({ service: ["worker", "voice"], mount: "root" });
    expect(parseLabels("service")).toBeNull();
  });
});
