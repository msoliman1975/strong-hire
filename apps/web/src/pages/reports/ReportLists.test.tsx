/** NV-4: the v2 Reports page's three lists (gap reports, interview debriefs, stories). */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { ReportItem } from "../../api/types";
import type { Story } from "../stories/api";
import { debriefResult, DebriefList, GapReportList, parseView, StoryList } from "./ReportLists";

const JOB_A = "00000000-0000-4000-8000-0000000000a1";

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
  report({
    type: "interview_debrief",
    match_score: null,
    interview_type: "behavioral",
    mode: "realistic",
    status: "ready",
    hire_signal: "Hire",
    duration_min: 10,
    ...over,
  });

const story = (over: Partial<Story>): Story =>
  ({
    id: crypto.randomUUID(),
    title: "Checkout migration",
    status: "draft",
    display_status: "draft",
    style: null,
    skills: [],
    notes: [],
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    ...over,
  }) as Story;

const inRouter = (node: React.ReactNode) => render(<MemoryRouter>{node}</MemoryRouter>);
const rows = (name: string) => within(screen.getByRole("list", { name })).getAllByRole("link");

describe("NV-4: gap reports", () => {
  it("NV-4: one row per gap report with the role, resume, match and date; the row opens the report", () => {
    const a = report({ id: "g1", match_score: 72 });
    const b = report({ id: "g2", job_name: "Shopify · Staff Engineer", resume_name: null, match_score: null, at: "2026-10-18T10:00:00Z" });
    inRouter(<GapReportList reports={[a, b]} />);
    const [first, second] = rows("Gap reports");
    expect(first).toHaveAttribute("href", expect.stringContaining("g1"));
    expect(first).toHaveTextContent("Stripe · Senior Engineer");
    expect(first).toHaveTextContent("Resume: Senior SWE resume");
    expect(first).toHaveTextContent("Match 72");
    expect(first).toHaveTextContent(/Oct 20/);
    expect(first).toHaveAccessibleName(/^Gap report: Stripe · Senior Engineer, match 72, /);
    expect(second).toHaveTextContent("Match —");
    // Plain rows: no cards, no tiles.
    expect(document.querySelector(".sx-summary, .sx-stat")).toBeNull();
  });

  it("NV-4: a deleted role and resume are named as deleted; none says so", () => {
    inRouter(<GapReportList reports={[report({ job_deleted: true, job_name: null, resume_deleted: true })]} />);
    expect(rows("Gap reports")[0]).toHaveTextContent(/deleted/i);
    document.body.innerHTML = "";
    inRouter(<GapReportList reports={[]} />);
    expect(screen.getByText(/No gap reports yet/)).toBeInTheDocument();
  });
});

describe("NV-4: interview debriefs", () => {
  it("NV-4: one row per debrief with the role, interview, mode, length, result and date", () => {
    inRouter(<DebriefList reports={[debrief({ id: "d1" })]} />);
    const [row] = rows("Interview debriefs");
    expect(row).toHaveAttribute("href", expect.stringContaining("d1"));
    expect(row).toHaveTextContent("Stripe · Senior Engineer");
    expect(row).toHaveTextContent(/Behavioral · Realistic · 10 min/);
    expect(row).toHaveTextContent("Hire");
  });

  it("NV-4: the result reads Scoring, Scoring failed or the hire signal", () => {
    expect(debriefResult(debrief({ status: "scoring" as ReportItem["status"] }))).toEqual({ text: "Scoring", tone: "plain" });
    expect(debriefResult(debrief({ status: "failed" }))).toEqual({ text: "Scoring failed", tone: "bad" });
    expect(debriefResult(debrief({ hire_signal: "Strong Hire" })).tone).toBe("ok");
    expect(debriefResult(debrief({ hire_signal: "Lean Hire" })).tone).toBe("warn");
    expect(debriefResult(debrief({ hire_signal: "No Hire" })).tone).toBe("bad");
  });
});

describe("NV-4: stories", () => {
  it("NV-4: every story, the last edited first, with its status in words; the row opens the story", () => {
    inRouter(
      <StoryList
        stories={[
          story({ id: "s1", title: "Old draft", updated_at: "2026-10-01T10:00:00Z" }),
          story({ id: "s2", title: "Proven one", status: "proven", display_status: "proven", style: "star", skills: ["ownership"], updated_at: "2026-10-09T10:00:00Z" }),
          story({ id: "s3", title: "Ready one", display_status: "ready", style: "carl", updated_at: "2026-10-05T10:00:00Z" }),
        ]}
      />,
    );
    const all = rows("Stories");
    expect(all.map((r) => r.querySelector(".rp-row__title")?.textContent)).toEqual(["Proven one", "Ready one", "Old draft"]);
    expect(all[0]).toHaveAttribute("href", "/stories/s2");
    expect(all[0]).toHaveTextContent("Proven");
    expect(all[0]).toHaveTextContent(/STAR · Ownership/);
    expect(all[1]).toHaveTextContent("Ready");
    expect(all[1]).toHaveTextContent("CARL");
    expect(all[2]).toHaveTextContent("Draft");
    expect(all[2]).toHaveTextContent("Classic");
    expect(all[2]).toHaveAccessibleName(/^Story: Old draft, Draft, edited /);
  });

  it("NV-4: with no stories it says how to start", () => {
    inRouter(<StoryList stories={[]} />);
    expect(screen.getByText(/No stories yet/)).toBeInTheDocument();
  });
});

describe("NV-4: the view in the URL", () => {
  it("NV-4: ?type= picks the list; old report-type links keep working; gap reports by default", () => {
    expect(parseView(null)).toBe("gap_report");
    expect(parseView("interview_debrief")).toBe("interview_debrief");
    expect(parseView("stories")).toBe("stories");
    expect(parseView("nope")).toBe("gap_report");
  });
});
