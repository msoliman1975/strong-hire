/**
 * The interviewer on screen (P10): a 3D head that talks with the interviewer's voice. three.js and
 * the lip-sync worklet load only on this page. Without WebGL, or if the scene fails, a flat face
 * shows the same states. The captions stay the text alternative; the avatar is decoration.
 *
 * Model files: public/avatar/interviewer-female.glb and interviewer-male.glb, faces made from
 * Microsoft Rocketbox avatars (MIT) by scripts/avatar/convert-rocketbox.mjs. The face matches the
 * interviewer's voice. If a file cannot be loaded, the built-in head is used.
 */
import { useEffect, useRef, useState } from "react";

import type { AgentActivity, InterviewerVoice } from "../voice";
import type { LipSync } from "./lipsync";
import type { AvatarScene } from "./scene";

export const avatarModelUrl = (voice: InterviewerVoice) => `/avatar/interviewer-${voice}.glb`;

export const activityLabel: Record<AgentActivity, string> = {
  idle: "Joining",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

const hasWebGL = () => {
  if (typeof WebGL2RenderingContext === "undefined") return false;
  try {
    return document.createElement("canvas").getContext("webgl2") !== null;
  } catch {
    return false;
  }
};

const prefersReducedMotion = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function InterviewerAvatar({
  activity,
  audioTrack,
  voice,
}: {
  activity: AgentActivity;
  audioTrack: MediaStreamTrack | null;
  /** null until the agent says. An agent that never says (an older version) gets the female face. */
  voice: InterviewerVoice | null;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<AvatarScene | null>(null);
  const [webgl] = useState(hasWebGL);
  const [ready, setReady] = useState<boolean | "failed">(false);
  const mode = !webgl || ready === "failed" ? "flat" : ready ? "3d" : "loading";
  const face = voice ?? (activity === "idle" ? null : "female");

  useEffect(() => {
    if (!webgl || !face || !canvas.current) return;
    let gone = false;
    const target = canvas.current;
    void (async () => {
      try {
        const { createAvatarScene } = await import("./scene");
        const created = await createAvatarScene(target, {
          modelUrl: avatarModelUrl(face),
          reducedMotion: prefersReducedMotion(),
        });
        if (gone) return created.dispose();
        scene.current = created;
        setReady(true);
      } catch {
        if (!gone) setReady("failed");
      }
    })();
    return () => {
      gone = true;
      scene.current?.dispose();
      scene.current = null;
      setReady(false);
    };
  }, [webgl, face]);

  useEffect(() => scene.current?.setActivity(activity), [activity, mode]);

  useEffect(() => {
    if (!audioTrack || mode !== "3d") return;
    let lipSync: LipSync | null = null;
    let gone = false;
    void import("./lipsync")
      .then(({ startLipSync }) => startLipSync(audioTrack))
      .then((l) => {
        if (gone) return l.stop();
        lipSync = l;
        scene.current?.setLipSync(l);
      })
      .catch(() => undefined); // the scene falls back to a talking rhythm
    return () => {
      gone = true;
      scene.current?.setLipSync(null);
      lipSync?.stop();
    };
  }, [audioTrack, mode]);

  return (
    <figure className="avatar" data-activity={activity} data-mode={mode} data-testid="interviewer-avatar">
      {mode === "flat" ? (
        <div className="avatar__flat" aria-hidden="true">
          <span className="avatar__eyes" />
          <span className="avatar__mouth" />
        </div>
      ) : (
        <canvas ref={canvas} className="avatar__canvas" aria-hidden="true" />
      )}
      <figcaption className="avatar__state">
        <span className="avatar__dot" aria-hidden="true" />
        Interviewer: {activityLabel[activity]}
      </figcaption>
    </figure>
  );
}
