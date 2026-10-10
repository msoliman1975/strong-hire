/**
 * Mouth movement from the interviewer's audio, all in the browser. HeadAudio (MIT) runs in an
 * audio worklet and reports Oculus viseme weights. If it cannot start, the audio level opens the
 * jaw instead. Nothing is recorded or sent anywhere: the audio only feeds these two nodes.
 */
import modelUrl from "@met4citizen/headaudio/dist/model-en-mixed.bin?url";
import workletUrl from "@met4citizen/headaudio/dist/headworklet.min.mjs?url";

import { poseFromLevel, poseFromVisemes, type MouthPose, type VisemeWeights } from "./visemes";

export interface LipSync {
  /** Call once per animation frame. */
  pose: (dtMs: number) => MouthPose;
  stop: () => void;
}

export async function startLipSync(track: MediaStreamTrack): Promise<LipSync> {
  const context = new AudioContext();
  const source = context.createMediaStreamSource(new MediaStream([track]));
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const level = () => {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const s of samples) sum += s * s;
    return Math.sqrt(sum / samples.length) * 4;
  };

  const weights: VisemeWeights = {};
  let head: import("@met4citizen/headaudio/dist/headaudio.min.mjs").HeadAudio | null = null;
  try {
    const { HeadAudio } = await import("@met4citizen/headaudio/dist/headaudio.min.mjs");
    await context.audioWorklet.addModule(workletUrl);
    head = new HeadAudio(context, {
      // The interviewer is a TTS voice with no background noise, so the energy gate is enough.
      // silMode 0: use the trained silence shapes, no calibration step.
      parameterData: { vadGateActiveDb: -40, vadGateInactiveDb: -55, silMode: 0 },
    });
    await head.loadModel(modelUrl);
    head.onvalue = (key, value) => {
      weights[key as keyof VisemeWeights] = value;
    };
    source.connect(head);
  } catch {
    head = null; // the level fallback below still moves the mouth
  }
  if (context.state === "suspended") await context.resume().catch(() => undefined);

  return {
    pose: (dtMs) => {
      if (!head) return poseFromLevel(level());
      head.update(dtMs);
      return poseFromVisemes(weights);
    },
    stop: () => {
      head?.stop();
      source.disconnect();
      void context.close();
    },
  };
}
