/** Types for @met4citizen/headaudio (MIT), which ships JavaScript only. Only the parts lipsync.ts uses. */
declare module "@met4citizen/headaudio/dist/headaudio.min.mjs" {
  export class HeadAudio extends AudioWorkletNode {
    constructor(
      context: BaseAudioContext,
      options?: { processorOptions?: Record<string, unknown>; parameterData?: Record<string, number> },
    );
    onvalue: ((key: string, value: number) => void) | null;
    loadModel(url: string, reset?: boolean): Promise<void>;
    update(dtMs: number): void;
    stop(): void;
  }
}
