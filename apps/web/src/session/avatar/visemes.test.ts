/** IV-10: the avatar's mouth shapes from viseme weights and from the audio level. */
import { describe, expect, it } from "vitest";

import { REST_POSE, arkitFromPose, easePose, poseFromLevel, poseFromVisemes } from "./visemes";

describe("IV-10 mouth pose", () => {
  it("opens the mouth for an open vowel and closes it for p, b, m", () => {
    expect(poseFromVisemes({ viseme_aa: 1 }).open).toBe(1);
    const pp = poseFromVisemes({ viseme_PP: 1 });
    expect(pp.open).toBe(0);
    expect(pp.closed).toBe(1);
  });

  it("rounds the lips for o and u", () => {
    expect(poseFromVisemes({ viseme_O: 1 }).round).toBe(1);
    expect(poseFromVisemes({ viseme_U: 0.5 }).round).toBe(0.5);
  });

  it("rests on silence and keeps mixed weights in range", () => {
    expect(poseFromVisemes({ viseme_sil: 1 })).toEqual(REST_POSE);
    const mixed = poseFromVisemes({ viseme_aa: 1, viseme_O: 1, viseme_E: 1 });
    for (const value of Object.values(mixed)) expect(value).toBeLessThanOrEqual(1);
  });

  it("opens the jaw with the audio level when there are no visemes", () => {
    expect(poseFromLevel(0).open).toBe(0);
    expect(poseFromLevel(0.3).open).toBeCloseTo(0.48);
    expect(poseFromLevel(5).open).toBe(1);
  });

  it("eases toward the target and reaches it over time", () => {
    const target = { ...REST_POSE, open: 1 };
    const step = easePose(REST_POSE, target, 16);
    expect(step.open).toBeGreaterThan(0);
    expect(step.open).toBeLessThan(1);
    let pose = REST_POSE;
    for (let i = 0; i < 60; i++) pose = easePose(pose, target, 16);
    expect(pose.open).toBeCloseTo(1, 3);
  });

  it("maps the pose to ARKit shapes without a full yawn", () => {
    const shapes = arkitFromPose({ open: 1, wide: 0, round: 0, closed: 0 });
    expect(shapes.jawOpen).toBeGreaterThan(0.3);
    expect(shapes.jawOpen).toBeLessThan(0.7);
    expect(arkitFromPose({ ...REST_POSE, closed: 1 }).mouthPressLeft).toBeGreaterThan(0);
  });
});
