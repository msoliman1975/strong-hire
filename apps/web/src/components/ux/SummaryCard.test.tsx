/** RSD-5: the shared card shell and its stat tiles (spec D-2, D-3). */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AddCard, SummaryCard, type StatTileProps } from "./SummaryCard";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "ux.css"), "utf-8");

const STATS: readonly [StatTileProps, StatTileProps, StatTileProps] = [
  { value: 7, label: "roles" },
  { value: 4, label: "open issues", tone: "warn", markLabel: "Includes high-severity issues" },
  { value: 18, label: "story ideas", tone: "teal" },
];

function renderCard(props: Partial<Parameters<typeof SummaryCard>[0]> = {}) {
  return render(
    <MemoryRouter>
      <SummaryCard
        title="Senior SWE resume"
        chip={<span className="sx-chip dark">Default</span>}
        stats={STATS}
        meta="Added Oct 28, 2026 · Edited Oct 28"
        primary={
          <a className="sx-btn sm" href="/resumes/r1/check">
            Show details
          </a>
        }
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("SummaryCard", () => {
  it("RSD-5: is a section named by its h2 title, with the chip, three tiles, the meta and the footer", () => {
    renderCard();
    const card = screen.getByRole("region", { name: "Senior SWE resume" });
    expect(within(card).getByRole("heading", { level: 2, name: "Senior SWE resume" })).toBeInTheDocument();
    expect(within(card).getByText("Default")).toBeInTheDocument();
    const terms = within(card).getAllByRole("term").map((t) => t.textContent);
    expect(terms).toEqual(["roles", "open issues", "story ideas"]);
    const values = within(card).getAllByRole("definition").map((d) => d.textContent);
    expect(values).toEqual(["7", "4", "18"]);
    expect(within(card).getByText("Added Oct 28, 2026 · Edited Oct 28")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Show details" })).toBeInTheDocument();
  });

  it.each(["neutral", "warn", "teal"] as const)("RSD-5: draws a %s tile with its tone class", (tone) => {
    const { container } = renderCard({
      stats: [
        { value: 1, label: "a", tone },
        { value: 2, label: "b" },
        { value: 3, label: "c" },
      ],
    });
    const tile = container.querySelector(".sx-stat");
    expect(tile).toHaveClass(`sx-stat--${tone}`);
    expect(tile).toHaveAttribute("data-tone", tone);
  });

  it("RSD-5: the warn tile announces the ▲ mark with its spoken label", () => {
    renderCard();
    const mark = screen.getByRole("img", { name: "Includes high-severity issues" });
    expect(mark.closest(".sx-stat")).toHaveClass("sx-stat--warn");
  });

  it("RSD-5: an unknown value shows a muted dash", () => {
    renderCard({
      stats: [
        { value: "—", label: "match" },
        { value: 1, label: "interview" },
        { value: "—", label: "days left" },
      ],
    });
    const dashes = screen.getAllByText("—");
    expect(dashes).toHaveLength(2);
    for (const d of dashes) expect(d).toHaveClass("is-unknown");
  });

  it("RSD-5: nothing inside the stats is focusable or interactive", () => {
    const { container } = renderCard();
    const stats = container.querySelector(".sx-summary__stats");
    expect(stats).not.toBeNull();
    expect(stats!.querySelectorAll("a, button, input, select, textarea, [tabindex]")).toHaveLength(0);
  });

  it("RSD-5: the loading state draws empty tiles and hides the numbers", () => {
    const { container } = renderCard({ loading: true, meta: "Strova is reading this resume." });
    const card = screen.getByRole("region", { name: "Senior SWE resume" });
    expect(card).toHaveAttribute("aria-busy", "true");
    expect(within(card).queryAllByRole("term")).toHaveLength(0);
    expect(within(card).queryByText("7")).toBeNull();
    expect(container.querySelectorAll(".sx-stat--empty")).toHaveLength(3);
    expect(container.querySelector(".sx-summary__stats--loading")).toHaveAttribute("aria-hidden", "true");
    expect(within(card).getByText("Strova is reading this resume.")).toBeInTheDocument();
  });

  it("RSD-5: the actions slot sits on the right of the footer, after Show details", () => {
    const { container } = renderCard({
      actions: (
        <>
          <button type="button" className="sx-btn quiet sm">
            Rename
          </button>
          <button type="button" className="sx-btn quiet sm danger">
            Delete
          </button>
        </>
      ),
    });
    const foot = container.querySelector(".sx-summary__foot")!;
    const controls = [...foot.querySelectorAll("a, button")].map((el) => el.textContent);
    expect(controls).toEqual(["Show details", "Rename", "Delete"]);
    expect(within(foot as HTMLElement).getByRole("button", { name: "Rename" }).parentElement).toHaveClass(
      "sx-summary__actions",
    );
  });

  it("RSD-5: a card with only actions still has a footer, and the card is never a link (D-2)", () => {
    const { container } = renderCard({
      primary: undefined,
      actions: (
        <button type="button" className="sx-btn quiet sm">
          Rename
        </button>
      ),
    });
    expect(container.querySelector(".sx-summary__foot")).not.toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("region").closest("a")).toBeNull();
  });

  it("RSD-5: renders the body slot (the readiness bars on a role)", () => {
    renderCard({ children: <div data-testid="bars">Coding 70%</div> });
    expect(within(screen.getByRole("region")).getByTestId("bars")).toBeInTheDocument();
  });
});

describe("AddCard", () => {
  it("RSD-5: is a link with the title and hint that ends a grid", () => {
    render(
      <MemoryRouter>
        <AddCard to="/resumes/new" title="Add a resume" hint="2 slots left." />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /Add a resume/ });
    expect(link).toHaveAttribute("href", "/resumes/new");
    expect(link).toHaveClass("sx-summary-add");
    expect(within(link).getByText("2 slots left.")).toBeInTheDocument();
  });
});

describe("RSD-5: the card shell CSS", () => {
  const block = css.slice(css.indexOf("RSD-5: the shared card shell"));

  it("uses tokens only: no literal colours", () => {
    expect(block.length).toBeGreaterThan(100);
    expect(block).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(block).not.toMatch(/rgba?\(/);
  });

  it("draws tiles on the ground fill, 12 px radius, with a mono 26 px value", () => {
    expect(block).toMatch(/\.sx-stat \{[^}]*background: var\(--sh-ground\);[^}]*border-radius: 12px;/);
    expect(block).toMatch(/\.sx-stat dd \{[^}]*font: 600 26px\/1\.1 var\(--sh-font-mono\);/);
  });

  it("keeps two columns only while each card is at least 400 px wide, so footers stay on one line", () => {
    expect(block).toMatch(/\.sx-grid2\.stretch \{ grid-template-columns: repeat\(auto-fill, minmax\(min\(100%, 400px\), 1fr\)\); \}/);
  });

  it("stretches the grid and puts a top rule on the wrapping footer", () => {
    expect(block).toMatch(/\.sx-grid2\.stretch \{ align-items: stretch; \}/);
    expect(block).toMatch(/\.sx-summary__foot \{[^}]*flex-wrap: wrap;[^}]*border-top: 1px solid var\(--sh-line\);/);
  });
});
