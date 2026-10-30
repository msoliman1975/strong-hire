/** Dev builds only: every Strova mode at every size, for the fidelity check against
 * docs/ux-strova/reference/strova-avatar.html (U02). */
import { Strova, STROVA_MODES, type StrovaHat, type StrovaMode } from "../components/strova";

const SIZES = [160, 104, 72, 40, 28, 18];
// The same rows as the reference sheet: every mode, then thinking in the interviewer hat.
const ROWS: { mode: StrovaMode; hat?: StrovaHat; title: string }[] = [
  ...STROVA_MODES.map((mode) => ({ mode, title: mode })),
  { mode: "thinking", hat: "interviewer", title: "thinking (interviewer hat)" },
];

export function StrovaPreviewPage() {
  return (
    <main style={{ padding: 32, background: "#f4f3f8", color: "#17161f", minHeight: "100vh", font: "15px/1.5 system-ui, sans-serif" }}>
      <h1 style={{ margin: "0 0 24px", fontSize: 26 }}>Strova avatar preview</h1>
      {ROWS.map((row) => (
        <section
          key={row.title}
          data-row={row.title}
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 28,
            flexWrap: "wrap",
            padding: 20,
            marginBottom: 16,
            background: "#fff",
            border: "1px solid #e2e0ea",
            borderRadius: 16,
          }}
        >
          <h2 style={{ width: 140, margin: 0, fontSize: 16 }}>{row.title}</h2>
          {SIZES.map((size) => (
            <div
              key={size}
              style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, fontSize: 12, color: "#5e5b6b" }}
            >
              <Strova mode={row.mode} hat={row.hat} size={size} />
              <span>{size} px</span>
            </div>
          ))}
        </section>
      ))}
    </main>
  );
}
