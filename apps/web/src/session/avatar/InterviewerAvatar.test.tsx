/** IV-10: the interviewer avatar shows the agent's activity. jsdom has no WebGL, so the flat face shows. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InterviewerAvatar, avatarModelUrl } from "./InterviewerAvatar";

describe("IV-10 interviewer avatar", () => {
  it("uses the flat face without WebGL and names the activity", () => {
    const { rerender } = render(<InterviewerAvatar activity="listening" audioTrack={null} voice="male" />);
    const avatar = screen.getByTestId("interviewer-avatar");
    expect(avatar).toHaveAttribute("data-mode", "flat");
    expect(avatar).toHaveTextContent("Interviewer: Listening");

    rerender(<InterviewerAvatar activity="speaking" audioTrack={null} voice="male" />);
    expect(avatar).toHaveAttribute("data-activity", "speaking");
    expect(avatar).toHaveTextContent("Interviewer: Speaking");
  });

  it("hides the face from screen readers; the captions carry the words", () => {
    const { container } = render(<InterviewerAvatar activity="thinking" audioTrack={null} voice="male" />);
    expect(container.querySelector(".avatar__flat")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("IV-10 face for the voice", () => {
  it("names one model file per voice", () => {
    expect(avatarModelUrl("female")).toBe("/avatar/interviewer-female.glb");
    expect(avatarModelUrl("male")).toBe("/avatar/interviewer-male.glb");
  });
});
