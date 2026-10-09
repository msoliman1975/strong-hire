/** The microphone check before the interview (P10): permission, a working device, and sound. */

export type MicProblem = "blocked" | "missing" | "busy" | "unsupported";

export const micProblemText: Record<MicProblem, string> = {
  blocked:
    "Your browser blocked the microphone. Allow it for this site with the icon in the address bar, then try again.",
  missing: "We found no microphone. Connect one, then try again.",
  busy: "Another app is using your microphone. Close it, then try again.",
  unsupported: "This browser cannot use a microphone here. Use a recent Chrome, Edge, Firefox or Safari.",
};

export function micProblem(err: unknown): MicProblem {
  const name = err instanceof Error || err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return "blocked";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "missing";
  if (name === "NotReadableError" || name === "AbortError") return "busy";
  return "unsupported";
}

export interface MicCheck {
  /** Sound level from 0 to 1. */
  level: () => number;
  stop: () => void;
}

/** Asks for the microphone and measures its level. Throws when it cannot (see micProblem). */
export async function openMicrophone(): Promise<MicCheck> {
  if (!globalThis.navigator?.mediaDevices?.getUserMedia) throw new Error("unsupported");
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const stopTracks = () => stream.getTracks().forEach((t) => t.stop());
  if (typeof AudioContext === "undefined") return { level: () => 1, stop: stopTracks };
  const context = new AudioContext();
  // Browsers may create it suspended; this runs from a click, so it may start.
  await context.resume().catch(() => undefined);
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);
  return {
    level: () => {
      analyser.getByteTimeDomainData(samples);
      let peak = 0;
      for (const v of samples) peak = Math.max(peak, Math.abs(v - 128));
      return Math.min(1, peak / 64);
    },
    stop: () => {
      stopTracks();
      void context.close();
    },
  };
}
