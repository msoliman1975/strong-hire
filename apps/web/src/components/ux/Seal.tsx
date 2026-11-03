/**
 * SV-13: the seals of earned results, in the brand's ring shape and the celebrating green.
 * - Verdict seal: a closed green ring with a check, for Hire and Strong Hire.
 * - Proven seal: Strova's thinking zigzag, frozen and filled green with a white check: her
 *   thinking turned into a stamp. For Proven stories.
 * Both are decorative (aria-hidden): the word beside them ("Hire", "Proven") carries the meaning.
 */
export const SEAL_TEETH = 12;

/** The filled zigzag in a 48 x 48 box: 2 x SEAL_TEETH points alternating radius 22.5 and 19. */
export const SEAL_PATH = (() => {
  const n = SEAL_TEETH * 2;
  let d = "";
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const r = i % 2 ? 19 : 22.5;
    d += `${i ? "L" : "M"}${(24 + r * Math.cos(a)).toFixed(2)} ${(24 + r * Math.sin(a)).toFixed(2)} `;
  }
  return `${d}Z`;
})();

const CHECK = "M15.5 24.5 L21.5 30.5 L33 18";

export function VerdictSeal({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg className={`sx-seal${className ? ` ${className}` : ""}`} data-seal="verdict" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <circle cx={24} cy={24} r={20} className="sx-seal__soft" />
      <circle cx={24} cy={24} r={20} fill="none" className="sx-seal__ink" strokeWidth={4} />
      <path d={CHECK} fill="none" className="sx-seal__ink" strokeWidth={4.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ProvenSeal({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg className={`sx-seal${className ? ` ${className}` : ""}`} data-seal="proven" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path d={SEAL_PATH} className="sx-seal__fill" />
      <path d={CHECK} fill="none" stroke="#ffffff" strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
