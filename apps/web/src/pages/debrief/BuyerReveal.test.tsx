/** RP-9: the debrief shows what the buyer was hiding, only when the API sends it. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BuyerReveal } from "./BuyerReveal";

const reveal = {
  scenario: "discovery_call" as const,
  persona_name: "Dana Ruiz",
  persona_title: "VP of Operations",
  company_summary: "A freight broker with 300 staff.",
  product: "A dispatch scheduling tool",
  product_illustrative: true,
  situation: "Dana booked the call after a webinar.",
  hidden_pains: ["Dispatchers rebuild the schedule by hand every morning"],
  budget: "About 40,000 dollars a year",
  decision_process: "Dana decides with the CFO",
  objections: [{ text: "We tried a tool and nobody used it.", when: "early" }],
  curveball: null,
  success_condition: "Dana agrees to a demo next week",
};
const buyer = { name: "Dana Ruiz", title: "VP of Operations", company_summary: "A freight broker.", product: "A tool" };

describe("buyer reveal", () => {
  it("RP-9: lists the hidden problems, the objections and what earned the next step", () => {
    render(<BuyerReveal buyer={{ ...buyer, reveal }} />);
    expect(screen.getByRole("heading", { name: "What Dana Ruiz was hiding" })).toBeInTheDocument();
    expect(screen.getByText("Dispatchers rebuild the schedule by hand every morning")).toBeInTheDocument();
    expect(screen.getByText(/We tried a tool and nobody used it\./)).toBeInTheDocument();
    expect(screen.getByText("Dana agrees to a demo next week")).toBeInTheDocument();
    expect(screen.getByText("Discovery call")).toBeInTheDocument();
  });

  it("RP-9: shows nothing while the brief is still hidden or for other types", () => {
    const { container, rerender } = render(<BuyerReveal buyer={{ ...buyer, reveal: null }} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<BuyerReveal buyer={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
