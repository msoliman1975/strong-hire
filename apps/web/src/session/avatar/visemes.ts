/**
 * Mouth shapes for the interviewer avatar. HeadAudio (lipsync.ts) reports Oculus viseme weights
 * from the interviewer's audio. This module turns them into a small mouth pose, and the pose into
 * the blend shapes that a 3D model has: Oculus visemes, ARKit shapes, or the built-in head.
 */

export const VISEMES = [
  "viseme_aa",
  "viseme_E",
  "viseme_I",
  "viseme_O",
  "viseme_U",
  "viseme_PP",
  "viseme_SS",
  "viseme_TH",
  "viseme_DD",
  "viseme_FF",
  "viseme_kk",
  "viseme_nn",
  "viseme_RR",
  "viseme_CH",
  "viseme_sil",
] as const;

export type Viseme = (typeof VISEMES)[number];
export type VisemeWeights = Partial<Record<Viseme, number>>;

/** open: jaw and lips apart. wide: corners pulled out. round: lips pushed forward. closed: lips pressed. */
export interface MouthPose {
  open: number;
  wide: number;
  round: number;
  closed: number;
}

export const REST_POSE: MouthPose = { open: 0, wide: 0, round: 0, closed: 0 };

const SHAPES: Record<Viseme, MouthPose> = {
  viseme_aa: { open: 1, wide: 0.4, round: 0, closed: 0 },
  viseme_E: { open: 0.6, wide: 0.8, round: 0, closed: 0 },
  viseme_I: { open: 0.35, wide: 1, round: 0, closed: 0 },
  viseme_O: { open: 0.75, wide: 0, round: 1, closed: 0 },
  viseme_U: { open: 0.35, wide: 0, round: 1, closed: 0 },
  viseme_PP: { open: 0, wide: 0, round: 0, closed: 1 },
  viseme_SS: { open: 0.15, wide: 0.8, round: 0, closed: 0 },
  viseme_TH: { open: 0.3, wide: 0.4, round: 0, closed: 0 },
  viseme_DD: { open: 0.35, wide: 0.5, round: 0, closed: 0 },
  viseme_FF: { open: 0.15, wide: 0.3, round: 0, closed: 0.4 },
  viseme_kk: { open: 0.45, wide: 0.4, round: 0, closed: 0 },
  viseme_nn: { open: 0.25, wide: 0.4, round: 0, closed: 0 },
  viseme_RR: { open: 0.4, wide: 0, round: 0.5, closed: 0 },
  viseme_CH: { open: 0.35, wide: 0, round: 0.6, closed: 0 },
  viseme_sil: REST_POSE,
};

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

/** The weighted mix of the viseme shapes. Weights may add up to more than 1; the result stays in 0..1. */
export function poseFromVisemes(weights: VisemeWeights): MouthPose {
  const pose = { ...REST_POSE };
  for (const v of VISEMES) {
    const w = weights[v] ?? 0;
    if (w <= 0) continue;
    const s = SHAPES[v];
    pose.open += s.open * w;
    pose.wide += s.wide * w;
    pose.round += s.round * w;
    pose.closed += s.closed * w;
  }
  return { open: clamp01(pose.open), wide: clamp01(pose.wide), round: clamp01(pose.round), closed: clamp01(pose.closed) };
}

/** Without viseme data (no audio, or HeadAudio failed): the audio level, 0..1, opens the jaw. */
export const poseFromLevel = (level: number): MouthPose => ({ ...REST_POSE, open: clamp01(level * 1.6), wide: 0.3 });

/** Moves `from` toward `to`. `rate` is the share of the gap closed per 16 ms frame. */
export function easePose(from: MouthPose, to: MouthPose, dtMs: number, rate = 0.35): MouthPose {
  const k = 1 - Math.pow(1 - rate, dtMs / 16);
  return {
    open: from.open + (to.open - from.open) * k,
    wide: from.wide + (to.wide - from.wide) * k,
    round: from.round + (to.round - from.round) * k,
    closed: from.closed + (to.closed - from.closed) * k,
  };
}

/**
 * ARKit blend shape weights for a model that has no Oculus visemes. The factors keep the face
 * natural: a full jawOpen looks like a yawn.
 */
export function arkitFromPose(p: MouthPose): Record<string, number> {
  return {
    jawOpen: p.open * 0.55,
    mouthFunnel: p.round * 0.6,
    mouthPucker: p.round * (1 - p.open) * 0.7,
    mouthStretchLeft: p.wide * 0.35,
    mouthStretchRight: p.wide * 0.35,
    mouthClose: p.closed * 0.3,
    mouthPressLeft: p.closed * 0.5,
    mouthPressRight: p.closed * 0.5,
  };
}
