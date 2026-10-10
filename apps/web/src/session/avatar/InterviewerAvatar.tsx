/**
 * The interviewer on screen (P10): a 3D head that talks with the interviewer's voice. three.js and
 * the lip-sync worklet load only on this page. Without WebGL, or if the scene fails, a flat face
 * shows the same states. The captions stay the text alternative; the avatar is decoration.
 *
 * Model file: put a GLB head at public/avatar/interviewer.glb (see scene.ts for what it needs).
 * Without it the built-in head is used.
 */
import { useEffect, useRef, useState } from "react";

import type { AgentActivity } from "../voice";
import type { LipSync } from "./lipsync";
import type { AvatarScene } from "./scene";

export const AVATAR_MODEL_URL = "/avatar/interviewer.glb";

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
}: {
  activity: AgentActivity;
  audioTrack: MediaStreamTrack | null;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<AvatarScene | null>(null);
  const [webgl] = useState(hasWebGL);
  const [ready, setReady] = useState<boolean | "failed">(false);
  const mode = !webgl || ready === "failed" ? "flat" : ready ? "3d" : "loading";

  useEffect(() => {
    if (!webgl || !canvas.current) return;
    let gone = false;
    const target = canvas.current;
    void (async () => {
      try {
        const { createAvatarScene } = await import("./scene");
        const created = await createAvatarScene(target, {
          modelUrl: AVATAR_MODEL_URL,
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
    };
  }, [webgl]);

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
