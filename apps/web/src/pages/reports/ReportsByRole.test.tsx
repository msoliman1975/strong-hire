/** NV-4: the v2 Reports page groups reports by target role on the shared card shell (RSD-5). */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { ReportItem } from "../../api/types";
import { groupByRole, reportStats, REPORTS_PER_CARD, ReportsByRole, ROLE_DELETED } from "./ReportsByRole";

const JOB_A = "00000000-0000-4000-8000-0000000000a1";
const JOB_B = "00000000-0000-4000-8000-0000000000b1";

function report(over: Partial<ReportItem>): ReportItem {
  return {
    type: "gap_report",
    id: crypto.randomUUID(),
    job_target_id: JOB_A,
    job_name: "Stripe · Senior Engineer",
    job_deleted: false,
    resume_id: "r1",
    resume_name: "Senior SWE resume",
    resume_deleted: false,
    status: "ready",
    at: "2026-10-20T10:00:00Z",
    match_score: 72,
    hire_signal: null,
    interview_type: null,
    mode: null,
    duration_min: null,
    ...over,
  } as ReportItem;
}

const debrief = (over: Partial<ReportItem>) =>
  report({ type: "interview_debrief", match_score: null, interview_type: "behavioral", status: "ready", hire_signal: "Hire", duration_min: 10, ...over });

function renderList(reports: ReportItem[]) {
  render(
    <MemoryRouter>
      <ReportsByRole reports={reports} />
    </MemoryRouter>,
  );
}

describe("NV-4 Reports by target role", () => {
  it("NV-4: groups reports by role, newest role first, keeping each role's reports newest first", () => {
    const list = [
      debrief({ job_target_id: JOB_B, job_name: "Twilio · Staff Engineer", at: "2026-10-30T10:00:00Z" }),
      report({ at: "2026-10-28T10:00:00Z", match_score: 81 }),
      report({ job_target_id: JOB_B, job_name: "Twilio · Staff Engineer", at: "2026-10-25T10:00:00Z" }),
      report({ at: "2026-10-10T10:00:00Z", match_score: 60 }),
    ];
    const groups = groupByRole(list);
    expect(groups.map((g) => g.title)).toEqual(["Twilio · Staff Engineer", "Stripe · Senior Engineer"]);
    expect(groups[1].reports.map((r) => r.match_score)).toEqual([81, 60]);
    expect(reportStats(groups[1].reports).map((s) => [s.value, s.label])).toEqual([
      [81, "latest match"],
      [2, "gap reports"],
      [0, "debriefs"],
    ]);
    expect(reportStats([debrief({})]).map((s) => [s.value, s.label])).toEqual([
      ["—", "latest match"],
      [0, "gap reports"],
      [1, "debrief"],
    ]);
  });

  it("NV-4: each role is a card with the latest date, three tiles, the resume, its reports and a link to the role", () => {
    renderList([debrief({ at: "2026-10-30T10:00:00Z", id: "s1" }), report({ id: "g1", at: "2026-10-28T10:00:00Z" })]);
    const card = screen.getByRole("region", { name: "Stripe · Senior Engineer" });
    expect(card).toHaveTextContent("Latest Oct 30, 2026");
    expect(within(card).getAllByRole("term").map((t) => t.textContent)).toEqual(["latest match", "gap report", "debrief"]);
    expect(card).toHaveTextContent("Resume: Senior SWE resume");
    const rows = within(within(card).getByRole("list", { name: "Reports for Stripe · Senior Engineer" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Interview debrief" })).toHaveAttribute("href", "/sessions/s1/debrief");
    expect(within(rows[1]).getByRole("link", { name: "Gap report" })).toHaveAttribute("href", `/jobs/${JOB_A}/gap?report=g1`);
    expect(within(card).getByRole("link", { name: "Open target role: Stripe · Senior Engineer" })).toHaveAttribute(
      "href",
      `/roles/${JOB_A}`,
    );
  });

  it("NV-4: a card shows the first few reports, then Show all", async () => {
    const user = userEvent.setup();
    renderList(Array.from({ length: REPORTS_PER_CARD + 2 }, (_, i) => report({ at: `2026-10-${20 - i}T10:00:00Z` })));
    const card = screen.getByRole("region", { name: "Stripe · Senior Engineer" });
    expect(within(card).getAllByRole("listitem")).toHaveLength(REPORTS_PER_CARD);
    await user.click(within(card).getByRole("button", { name: `Show all ${REPORTS_PER_CARD + 2}` }));
    expect(within(card).getAllByRole("listitem")).toHaveLength(REPORTS_PER_CARD + 2);
    expect(within(card).getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
  });

  it("NV-4: a deleted role has no role link, and a deleted resume says so", () => {
    renderList([report({ job_deleted: true, job_name: null, resume_deleted: true, resume_name: null })]);
    const card = screen.getByRole("region", { name: ROLE_DELETED });
    expect(within(card).queryByRole("link", { name: /Open target role/ })).toBeNull();
    expect(card).toHaveTextContent("Resume deleted");
  });

  it("NV-4: with no reports it shows the empty card", () => {
    renderList([]);
    expect(screen.getByRole("heading", { name: "No reports yet" })).toBeInTheDocument();
  });
});
