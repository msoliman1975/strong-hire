/** DM-2: the debrief shows pace and fillers per answer, with a plain note outside the normal range. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Scorecard } from "../../api/types";
import { scorecardFor } from "../../mocks/fixtures";
import { DELIVERY_RANGES, DeliveryMetrics, deliveryNotes, NO_DELIVERY_NOTE } from "./DeliveryMetrics";

function withDelivery(values: (Scorecard["per_question"][number]["delivery"] | null)[]): Scorecard {
  const card = scorecardFor("behavioral", false);
  return {
    ...card,
    per_question: card.per_question.map((q, i) => ({ ...q, delivery: values[i] ?? null })),
  };
}

describe("DM-2 delivery metrics", () => {
  it("DM-2: shows pace, fillers and speaking time for each answer", () => {
    render(
      <DeliveryMetrics
        scorecard={withDelivery([
          { words_per_minute: 142, fillers_per_minute: 1.5, duration_seconds: 95 },
          { words_per_minute: 128.4, fillers_per_minute: 0, duration_seconds: 40 },
        ])}
      />,
    );
    expect(screen.getByRole("heading", { name: "Delivery" })).toBeInTheDocument();
    const rows = screen.getAllByTestId("delivery");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("142 words a minute");
    expect(rows[0]).toHaveTextContent("1.5 a minute");
    expect(rows[0]).toHaveTextContent("1 min 35 s");
    expect(rows[1]).toHaveTextContent("128.4 words a minute");
    expect(rows[1]).toHaveTextContent("40 s");
    expect(screen.queryByTestId("delivery-note")).toBeNull(); // all within range
  });

  it("DM-2: a plain note when pace or fillers are outside the normal range", () => {
    render(
      <DeliveryMetrics
        scorecard={withDelivery([
          { words_per_minute: 195, fillers_per_minute: 8, duration_seconds: 60 },
          { words_per_minute: 90, fillers_per_minute: 2, duration_seconds: 60 },
        ])}
      />,
    );
    const [fast, slow] = screen.getAllByTestId("delivery");
    const fastNotes = within(fast).getAllByTestId("delivery-note");
    expect(fastNotes).toHaveLength(2);
    expect(fastNotes[0]).toHaveTextContent(/^Faster than usual/);
    expect(fastNotes[1]).toHaveTextContent(/^More filler words than usual/);
    expect(within(slow).getByTestId("delivery-note")).toHaveTextContent(/^Slower than usual/);
  });

  it("DM-2: the ranges sit in one constant and the edges count as normal", () => {
    const edge = {
      words_per_minute: DELIVERY_RANGES.paceMaxWpm,
      fillers_per_minute: DELIVERY_RANGES.fillersMaxPerMin,
      duration_seconds: 30,
    };
    expect(deliveryNotes(edge)).toEqual([]);
    expect(deliveryNotes({ ...edge, words_per_minute: DELIVERY_RANGES.paceMinWpm })).toEqual([]);
  });

  it("DM-2: an answer without a spoken reply says it was not measured", () => {
    render(
      <DeliveryMetrics
        scorecard={withDelivery([{ words_per_minute: 140, fillers_per_minute: 1, duration_seconds: 60 }, null])}
      />,
    );
    expect(screen.getAllByTestId("delivery")[1]).toHaveTextContent("Not measured");
  });

  it("DM-2, PL-7: a typed session has no delivery metrics and says why", () => {
    render(<DeliveryMetrics scorecard={withDelivery([null, null])} />);
    expect(screen.getByTestId("delivery-none")).toHaveTextContent(NO_DELIVERY_NOTE);
    expect(screen.queryAllByTestId("delivery")).toHaveLength(0);
  });
});
