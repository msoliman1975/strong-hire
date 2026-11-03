/**
 * SV-12: the loading indicator is Strova's thinking ring, the zigzag ring she wears in her
 * thinking and analysing modes, drawn with fewer, deeper teeth so it reads at 16 to 24 px.
 * Waiting always looks like Strova thinking. Decorative: the text beside it says what is loading.
 * It turns once every 3 s and stops under reduced motion (ux.css).
 */
export const THINKING_TEETH = 12;

/** The zigzag in a 48 x 48 box: 2 x THINKING_TEETH points alternating radius 20 and 15. */
export const THINKING_PATH = (() => {
  const n = THINKING_TEETH * 2;
  let d = "";
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const r = i % 2 ? 15 : 20;
    d += `${i ? "L" : "M"}${(24 + r * Math.cos(a)).toFixed(2)} ${(24 + r * Math.sin(a)).toFixed(2)} `;
  }
  return `${d}Z`;
})();

export function ThinkingRing({ size = 20, hat = "coach" }: { size?: number; hat?: "coach" | "interviewer" }) {
  return (
    <svg className="sx-thinking" data-hat={hat} width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path d={THINKING_PATH} fill="none" strokeWidth={3.5} strokeLinejoin="round" />
    </svg>
  );
}
