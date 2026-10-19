/** Simulations (SM-1 to SM-5, SM-12, SM-13, SM-15, SM-16) against the admin mocks. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AppRoutes, createQueryClient } from "../App";
import { opsState } from "../mocks/controlsHandlers";
import { mockSignIn } from "../mocks/handlers";
import { mockStore } from "../mocks/node";
import { simState } from "../mocks/simHandlers";

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

async function openSimulations() {
  signInAdmin();
  const user = renderAt("/simulations");
  expect(await screen.findByRole("heading", { name: "Simulations", level: 1 })).toBeInTheDocument();
  await screen.findByRole("button", { name: "Start run" });
  await screen.findByRole("table");
  return user;
}

function rowOf(text: string | RegExp): HTMLElement {
  const cell = screen.getAllByRole("row").find((r) => within(r).queryByText(text));
  if (!cell) throw new Error(`no row with ${String(text)}`);
  return cell;
}

describe("Simulations page", () => {
  it("SM-12: is in the nav and lists admin and suite runs with cost and failed rules", async () => {
    await openSimulations();
    expect(
      within(screen.getByRole("navigation", { name: "Admin" })).getByRole("link", { name: "Simulations" }),
    ).toHaveAttribute("href", "/simulations");
    const done = rowOf("Ada Venn");
    expect(within(done).getByText("Done")).toBeInTheDocument();
    expect(within(done).getByText("no_repetition")).toBeInTheDocument();
    expect(within(done).getByText("$0.08")).toBeInTheDocument();
    expect(within(done).getByText("1200 ms")).toBeInTheDocument();
    expect(within(done).getByRole("link", { name: "Replay" })).toHaveAttribute(
      "href",
      "/simulations/replay/00000000-0000-4000-8000-0000000005e1",
    );
    const suite = rowOf("suite text-smoke");
    expect(within(suite).getByText("provider down")).toBeInTheDocument();
    expect(within(suite).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("SM-1: the form shows the persona's posting, the estimate, the budget; text hides voice-only behaviors", async () => {
    const user = await openSimulations();
    const form = within(screen.getByRole("region", { name: "New run" }));
    expect(screen.getByText("swe-stripe-backend")).toBeInTheDocument();
    expect(screen.getByText(/\$3\.75 left of \$5\.00/)).toBeInTheDocument();
    await user.selectOptions(form.getByLabelText("Length"), "10");
    expect(screen.getByText(/about \$0\.\d\d/)).toBeInTheDocument();
    await user.selectOptions(form.getByLabelText("Behavior"), "interrupts");
    await user.selectOptions(form.getByLabelText("Channel"), "text");
    expect(form.getByLabelText<HTMLSelectElement>("Behavior").value).toBe("normal");
    expect(form.getByRole<HTMLOptionElement>("option", { name: "Interrupts (voice only)" }).disabled).toBe(true);
    await user.selectOptions(form.getByLabelText("Persona"), "new-grad-swe");
    expect(screen.getByText("swe-northwind-newgrad")).toBeInTheDocument();
  });

  it("SM-2: Start queues a run that appears in the list, and the list polls", async () => {
    const user = await openSimulations();
    await user.selectOptions(screen.getByLabelText("Candidate quality"), "weak");
    await user.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText(/Run queued: Mira Ostrand/)).toBeInTheDocument();
    const queued = await screen.findByRole("row", { name: /Mira Ostrand/ });
    expect(within(queued).getByText("Queued")).toBeInTheDocument();
    expect(simState(mockStore.db).runs[0].scenario.quality).toBe("weak");
    expect(screen.getByText(/1 of 5 waiting/)).toBeInTheDocument();
  });

  it("SM-3: a closed gate is explained and Start is disabled; a 409 shows its reason", async () => {
    simState(mockStore.db).liveLimitReason = "3 real interviews are live; runs start below 3";
    await openSimulations();
    const why = screen.getByRole("status", { name: "Why a run cannot start" });
    expect(why).toHaveTextContent("3 real interviews are live");
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
  });

  it("SM-3: paused in Controls closes the gate with a link to Controls", async () => {
    opsState(mockStore.db).values.sim_paused = true;
    await openSimulations();
    const why = screen.getByRole("status", { name: "Why a run cannot start" });
    expect(why).toHaveTextContent("paused");
    expect(within(why).getByRole("link", { name: "Open Controls" })).toHaveAttribute("href", "/ops/controls");
  });

  it("SM-5: cancelling a queued run asks for a reason and ends it", async () => {
    const user = await openSimulations();
    await user.click(screen.getByRole("button", { name: "Start run" }));
    const row = await screen.findByRole("row", { name: /Mira Ostrand/ });
    await user.click(within(row).getByRole("button", { name: "Cancel" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel the run" });
    expect(dialog).toHaveTextContent("leaves the queue now");
    await user.type(within(dialog).getByLabelText(/Reason/), "wrong persona");
    await user.click(within(dialog).getByRole("button", { name: "Cancel run" }));
    expect(await within(await screen.findByRole("row", { name: /Mira Ostrand/ })).findByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("SM-13: Keep is a checkbox; deleting a kept run needs the word DELETE and leaves a stub", async () => {
    const user = await openSimulations();
    const row = rowOf("Ada Venn");
    await user.click(within(row).getByRole("checkbox", { name: /Keep run/ }));
    await expect.poll(() => simState(mockStore.db).runs[0].keep).toBe(true);
    await user.click(within(rowOf("Ada Venn")).getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete the run" });
    expect(dialog).toHaveTextContent("This run is marked Keep.");
    await user.type(within(dialog).getByLabelText(/Reason/), "bad audio");
    const confirm = within(dialog).getByRole("button", { name: "Delete run" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Type/), "DELETE");
    await user.click(confirm);
    expect(await screen.findByText(/Files deleted by admin@example.com: bad audio/)).toBeInTheDocument();
    expect(within(rowOf("Ada Venn")).queryByRole("link", { name: "Replay" })).not.toBeInTheDocument();
  });

  it("SM-12: filters by source and status", async () => {
    const user = await openSimulations();
    await user.selectOptions(screen.getByLabelText("Started by"), "suite");
    await expect.poll(() => screen.queryByText("Ada Venn")).toBeNull();
    expect(screen.getByText("suite text-smoke")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Started by"), "");
    await user.selectOptions(screen.getByLabelText("Status"), "done");
    await expect.poll(() => screen.queryByText("suite text-smoke")).toBeNull();
    expect(screen.getByText("Ada Venn")).toBeInTheDocument();
  });
});

const JOB = "Senior Data Engineer at Fjord Freight. Build the shipment event pipeline in Kafka.";
const CV = "Lena Ortiz. Data engineer, 7 years. Built streaming pipelines at a logistics firm.";

function newRunForm() {
  return within(screen.getByRole("region", { name: "New run" }));
}

describe("Pasted job and CV (SM-17, SM-18, SM-20, SM-21)", () => {
  it("SM-17, SM-18: a pasted job asks for a level before Start, and the run is tagged custom", async () => {
    const user = await openSimulations();
    const form = newRunForm();
    expect(form.queryByLabelText(/^Level/)).not.toBeInTheDocument();
    await user.click(form.getByLabelText("Job posting (optional)"));
    await user.paste(JOB);
    expect(form.getByText(/Pasted job/)).toBeInTheDocument();
    const start = form.getByRole("button", { name: "Start run" });
    expect(start).toBeDisabled();
    await user.selectOptions(form.getByLabelText("Level (required with a pasted job)"), "mid");
    await user.click(form.getByLabelText("CV (optional)"));
    await user.paste(CV);
    expect(form.getAllByText(`${CV.length} / 60,000 characters`)).toHaveLength(2); // both are 82 long
    expect(start).toBeEnabled();
    await user.click(start);
    const row = await screen.findByRole("row", { name: /Mira Ostrand/ });
    expect(row).toHaveTextContent("custom job, custom CV");
    const stored = simState(mockStore.db).runs[0];
    expect(stored.inputs).toEqual({ job_text: JOB, cv_text: CV, level: "mid" });
    expect(stored.scenario.level).toBe("mid");
  });

  it("SM-18: clearing the pasted job hides the level and drops it", async () => {
    const user = await openSimulations();
    const form = newRunForm();
    await user.click(form.getByLabelText("Job posting (optional)"));
    await user.paste(JOB);
    await user.selectOptions(form.getByLabelText("Level (required with a pasted job)"), "senior");
    await user.clear(form.getByLabelText("Job posting (optional)"));
    expect(form.queryByLabelText(/^Level/)).not.toBeInTheDocument();
    await user.click(form.getByRole("button", { name: "Start run" }));
    await screen.findByRole("row", { name: /Mira Ostrand/ });
    expect(simState(mockStore.db).runs[0].scenario.level).toBeNull();
    expect(simState(mockStore.db).runs[0].inputs).toBeNull();
  });

  it("SM-21: Run again fills the form with the run's settings and pasted texts", async () => {
    const state = simState(mockStore.db);
    state.runs[0] = {
      ...state.runs[0],
      scenario: { ...state.runs[0].scenario, quality: "weak", duration_min: 30, custom_job: true, level: "staff_principal" },
      inputs: { job_text: JOB, cv_text: null, level: "staff_principal" },
    };
    const user = await openSimulations();
    await user.click(within(rowOf("Ada Venn")).getByRole("button", { name: "Run again" }));
    expect(await screen.findByText(/Filled in from the run of Ada Venn/)).toBeInTheDocument();
    const form = newRunForm();
    expect(form.getByLabelText<HTMLTextAreaElement>("Job posting (optional)").value).toBe(JOB);
    expect(form.getByLabelText<HTMLTextAreaElement>("CV (optional)").value).toBe("");
    expect(form.getByLabelText<HTMLSelectElement>("Level (required with a pasted job)").value).toBe("staff_principal");
    expect(form.getByLabelText<HTMLSelectElement>("Candidate quality").value).toBe("weak");
    expect(form.getByLabelText<HTMLSelectElement>("Length").value).toBe("30");
  });

  it("SM-21: a deleted run's texts are gone, so Run again keeps only its settings", async () => {
    const state = simState(mockStore.db);
    state.runs[0] = {
      ...state.runs[0],
      deleted_at: "2026-10-19T10:00:00Z",
      deleted_by: "admin@example.com",
      scenario: { ...state.runs[0].scenario, custom_cv: true },
      inputs: null,
    };
    const user = await openSimulations();
    await user.click(within(rowOf("Ada Venn")).getByRole("button", { name: "Run again" }));
    expect(await screen.findByText(/Its pasted texts were deleted/)).toBeInTheDocument();
    expect(newRunForm().getByLabelText<HTMLTextAreaElement>("CV (optional)").value).toBe("");
  });
});

describe("Controls for sim runs (SM-15)", () => {
  it("pauses runs, and pausing can stop the active run", async () => {
    const state = simState(mockStore.db);
    state.runs[0] = { ...state.runs[0], status: "interviewing", finished_at: null };
    signInAdmin();
    const user = renderAt("/ops/controls");
    await screen.findByRole("heading", { name: "AI candidate runs (SM-15)" });
    const stop = await screen.findByRole("button", { name: "Pause and stop the active run" });
    await user.click(stop);
    const dialog = screen.getByRole("dialog", { name: "Pause sim runs and stop the active run" });
    await user.type(within(dialog).getByLabelText(/Reason/), "load test");
    await user.click(within(dialog).getByRole("button", { name: "Pause and stop" }));
    await expect.poll(() => opsState(mockStore.db).values.sim_paused).toBe(true);
    expect(await screen.findByText(/AI candidate runs paused/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume sim runs" })).toBeInTheDocument();
  });

  it("changes the live sessions limit (0 to 20)", async () => {
    signInAdmin();
    const user = renderAt("/ops/controls");
    const input = await screen.findByLabelText(/Live sessions limit for sim runs/);
    await user.clear(input);
    await user.type(input, "21");
    expect(screen.getByRole("button", { name: "Save limit" })).toBeDisabled();
    await user.clear(input);
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "Save limit" }));
    const dialog = screen.getByRole("dialog", { name: "Change the live sessions limit for sim runs" });
    expect(dialog).toHaveTextContent("no limit");
    await user.type(within(dialog).getByLabelText(/Reason/), "quiet night");
    await user.click(within(dialog).getByRole("button", { name: "Save limit" }));
    await expect.poll(() => opsState(mockStore.db).values.sim_max_live_sessions).toBe(0);
    expect(await screen.findByText(/ignore live interviews/)).toBeInTheDocument();
  });
});
