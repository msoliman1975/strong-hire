/** QB-1 to QB-3: the Questions page, against the MSW mocks of GET /questions. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import { COMPETENCIES_BY_TYPE } from "../api/questions";
import { createQueryClient } from "../App";
import { QuestionsPage } from "./QuestionsPage";

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

  it("the area filter knows every competency exactly once", () => {
    const openapi = JSON.parse(readFileSync(resolve(__dirname, "../../openapi.json"), "utf8")) as {
      components: { schemas: { Competency: { enum: string[] } } };
    };
    const listed = Object.values(COMPETENCIES_BY_TYPE).flat();
    expect(new Set(listed).size).toBe(listed.length);
    // RS-1: Recruiter screen is not a question bank type; this competency is only its own.
    const standard = openapi.components.schemas.Competency.enum.filter((c) => c !== "logistics_and_expectations");
    expect([...listed].sort()).toEqual(standard.sort());
  });
});
