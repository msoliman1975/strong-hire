/** UI-1: shared v2 pieces carry their meaning in text, never color alone. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CoachLine, CountdownBadge, Meter, Segmented, StoryPartChip } from "./ui";

describe("UI-1 shared pieces", () => {
  it("UI-1: a story part chip always writes its part name", () => {
    render(
      <>
        <StoryPartChip part="context" />
        <StoryPartChip part="stakes" />
        <StoryPartChip part="action" state="now" />
        <StoryPartChip part="result" />
        <StoryPartChip part="reflection" state="next" />
      </>,
    );
    for (const name of ["Context", "Stakes", "Your action", "Result", "Reflection"]) {
      expect(screen.getByText(name)).toHaveAttribute("class", "story-part");
    }
  });

  it("UI-1: the countdown reads as words", () => {
    const { rerender } = render(<CountdownBadge days={6} />);
    expect(screen.getByText("6 days left")).toBeInTheDocument();
    rerender(<CountdownBadge days={0} />);
    expect(screen.getByText("Today")).toHaveAttribute("data-soon", "true");
  });

  it("UI-1: the meter states the rubric score and its label", () => {
    render(<Meter score={3} />);
    expect(screen.getByText(/3 of 4/)).toHaveTextContent("3 of 4, Meets the bar");
  });

  it("UI-1: the coach line is a labeled region with the message", () => {
    render(<CoachLine>Want to build one now?</CoachLine>);
    expect(screen.getByRole("region", { name: "Your coach" })).toHaveTextContent("Want to build one now?");
  });

  it("UI-1: the segmented control marks the chosen option", () => {
    render(
      <Segmented
        label="Coaching style"
        value="gentle"
        onChange={() => {}}
        options={[
          { value: "gentle", label: "Gentle" },
          { value: "direct", label: "Direct" },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "Gentle" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Direct" })).toHaveAttribute("aria-pressed", "false");
  });
});
