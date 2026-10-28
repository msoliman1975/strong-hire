/** QB-1 to QB-3: the Questions page, against the MSW mocks of GET /questions. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { COMPETENCIES_BY_TYPE } from "../api/questions";
import { createQueryClient } from "../App";
import { competencyLabel } from "../labels";
import { setFeatureOverrides } from "../theme/features";
import { QuestionsPage } from "./QuestionsPage";

afterEach(() => setFeatureOverrides({}));

let lastSearch = "";
function LocationProbe() {
  const { search } = useLocation();
  useEffect(() => {
    lastSearch = search;
  }, [search]);
  return null;
}

function renderAt(path: string) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/questions"
            element={
              <>
                <QuestionsPage />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return user;
}

const section = async (name: RegExp) =>
  within((await screen.findByRole("heading", { name })).closest("section") as HTMLElement);

describe("questions page", () => {
  it("QB-1, QB-2: lists company and general questions with tags and key hints", async () => {
    renderAt("/questions");
    const company = await section(/^Company questions \(2\)/);
    expect(company.getByText("How would you design an idempotent payments API?")).toBeInTheDocument();
    expect(company.getAllByText("Stripe").length).toBeGreaterThan(0); // company tag when all are listed
    expect(company.getByText("Senior")).toBeInTheDocument();
    expect(company.getByText("How you handle quality")).toBeInTheDocument();
    expect(company.getAllByText("Strong signals and watch-outs").length).toBe(2);
    expect(company.getAllByRole("link", { name: "Where this question was reported" })[0]).toHaveAttribute(
      "href",
      "https://example.com/stripe-interview",
    );
    const general = await section(/^General questions \(3\)/);
    expect(general.getByText("Tell me about a time you disagreed with your manager.")).toBeInTheDocument();
    expect(general.queryByRole("link", { name: "Where this question was reported" })).toBeNull();
  });

  it("QB-3, QB-4: a company link shows its questions first, then 'Also common' with the same filters", async () => {
    renderAt("/questions?company=stripe&type=behavioral&area=conflict_handling");
    await section(/^Stripe questions \(0\)/);
    const common = await section(/^Also common \(1\)/);
    expect(common.getByText("Tell me about a time you disagreed with your manager.")).toBeInTheDocument();
    expect(screen.getByLabelText("Company")).toHaveValue("stripe");
    expect(screen.getByLabelText("Interview type")).toHaveValue("behavioral");
    expect(screen.getByRole("checkbox", { name: "Conflict handling" })).toBeChecked();
  });

  it("QB-1: General shows general questions only", async () => {
    renderAt("/questions?company=general");
    await section(/^General questions \(3\)/);
    expect(screen.queryByRole("heading", { name: /Company questions/ })).toBeNull();
  });

  it("QB-1: areas follow the interview type, and filters can be cleared", async () => {
    const user = renderAt("/questions");
    expect(await screen.findByText("Pick an interview type to filter by area.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Interview type"), "behavioral");
    await user.click(screen.getByRole("checkbox", { name: "Learning from failure" }));
    const general = await section(/^General questions \(1\)/);
    expect(general.getByText("Tell me about a project that failed. What did you learn?")).toBeInTheDocument();
    expect(lastSearch).toBe("?type=behavioral&area=learning_from_failure");

    // A new type drops the areas of the old one.
    await user.selectOptions(screen.getByLabelText("Interview type"), "case");
    expect(lastSearch).toBe("?type=case");
    expect(screen.queryByRole("checkbox", { name: "Learning from failure" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(lastSearch).toBe("");
  });

  it("QB-1: job category, level and text search", async () => {
    const user = renderAt("/questions");
    await user.selectOptions(await screen.findByLabelText("Job category"), "pm");
    await section(/^Company questions \(1\)/); // the swe/tpm question is left out
    await user.selectOptions(screen.getByLabelText("Level"), "new_grad");
    await section(/^Company questions \(1\)/);
    await user.type(screen.getByLabelText("Search"), "estimation");
    await section(/^General questions \(1\)/);
    expect(lastSearch).toContain("q=estimation");
  });

  it("the area filter knows every competency, once per standard type", () => {
    const openapi = JSON.parse(readFileSync(resolve(__dirname, "../../openapi.json"), "utf8")) as {
      components: { schemas: { Competency: { enum: string[] } } };
    };
    const { recruiter_screen: recruiter, ...standard } = COMPETENCIES_BY_TYPE;
    const listed = Object.values(standard).flat();
    expect(new Set(listed).size).toBe(listed.length);
    const all = new Set([...listed, ...recruiter]);
    expect([...all].sort()).toEqual([...openapi.components.schemas.Competency.enum].sort());
  });

  it("RS-1: with v2 on, Recruiter screen is a type with its own areas", async () => {
    setFeatureOverrides({ v2_enabled: true });
    const user = renderAt("/questions");
    await section(/^General questions/);
    await user.selectOptions(screen.getByLabelText("Interview type"), "recruiter_screen");
    expect(lastSearch).toContain("type=recruiter_screen");
    const areas = within(screen.getByRole("group", { name: "Question area" }));
    expect(areas.getAllByRole("checkbox").map((c) => c.closest("label")?.textContent)).toEqual([
      competencyLabel("motivation"),
      competencyLabel("role_fit"),
      competencyLabel("communication"),
      competencyLabel("logistics_and_expectations"),
    ]);
    // The bank holds no recruiter screen questions yet.
    expect((await screen.findAllByText("No questions match these filters.")).length).toBeGreaterThan(0);
  });

  it("RS-1: with v2 off, Recruiter screen is not offered", async () => {
    renderAt("/questions");
    await section(/^General questions/);
    const options = within(screen.getByLabelText("Interview type")).getAllByRole("option");
    expect(options.map((o) => o.getAttribute("value"))).not.toContain("recruiter_screen");
  });
});
