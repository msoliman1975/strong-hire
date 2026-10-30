/**
 * Strova, the one AI character (SV-1 to SV-5). A port of the approved `strova(mode, size)`
 * drawing in docs/ux-strova/reference/mockups.html: same paths, transforms and colours,
 * rendered as JSX. Animations live in strova.css.
 */
import { useId } from "react";

import { FACE, HAIR_BACK, HAIR_FRONT } from "./paths";
import "./strova.css";

export type StrovaMode =
  | "listening"
  | "speaking"
  | "interviewing"
  | "thinking"
  | "analysing"
  | "coaching"
  | "celebrating";

export type StrovaHat = "coach" | "interviewer";

export const STROVA_MODES: readonly StrovaMode[] = [
  "listening",
  "speaking",
  "interviewing",
  "thinking",
  "analysing",
  "coaching",
  "celebrating",
];

/** SV-4: the accessible name of each state. */
export const STROVA_LABELS: Record<StrovaMode, string> = {
  listening: "Strova is listening",
  speaking: "Strova is speaking",
  interviewing: "Strova is interviewing",
  thinking: "Strova is thinking",
  analysing: "Strova is analysing",
  coaching: "Strova is coaching",
  celebrating: "Strova is celebrating",
};

/** SV-2: the ring colour shows the hat (ux-spec section 4.1). */
export const STROVA_COLORS = {
  coach: { accent: "#5332e6", soft: "#eeeafe" },
  interviewer: { accent: "#0b6e8c", soft: "#e0f2f7" },
  celebrating: { accent: "#12775a", soft: "#e3f4ec" },
} as const;

/** SV-5: below this size only the face and ring show. */
export const STROVA_EFFECTS_MIN_SIZE = 64;

const INTERVIEWER_MODES: ReadonlySet<StrovaMode> = new Set(["interviewing", "speaking", "listening"]);

const HAIR = "#6b4226";
const SKIN = "#e8b996";
const SHADE = "#d6a37f";
const TOP = "#a99bdc";
const LINE = "#c9c5d6";
const HEAD_TRANSFORM = "translate(40 29.6) scale(1.2)";

/** The zigzag ring for thinking and analysing: 56 points alternating radius 96 and 90. */
export const ZIGZAG_PATH = (() => {
  const n = 56;
  let d = "";
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2;
    const r = i % 2 ? 90 : 96;
    d += `${i ? "L" : "M"}${(100 + r * Math.cos(a)).toFixed(1)} ${(100 + r * Math.sin(a)).toFixed(1)} `;
  }
  return `${d}Z`;
})();

const MOUTHS: Record<Exclude<StrovaMode, "speaking">, string> = {
  listening: "M94 116 Q100 117.5 106 116",
  thinking: "M93 117 Q99 115 107 118",
  analysing: "M91 116 L109 116",
  coaching: "M91 114 Q100 120 109 114",
  interviewing: "M91 116 L109 116",
  celebrating: "M91 114 Q100 120 109 114",
};

const round = { fill: "none", strokeLinecap: "round" } as const;

function Effects({ mode, accent }: { mode: StrovaMode; accent: string }) {
  switch (mode) {
    case "thinking":
      return (
        <g data-part="effects">
          <circle className="sv-box sv-dot" cx="150" cy="58" r="5" fill={accent} />
          <circle className="sv-box sv-dot sv-d2" cx="163" cy="42" r="7" fill={accent} />
          <circle className="sv-box sv-dot sv-d3" cx="178" cy="24" r="10" fill={accent} />
        </g>
      );
    case "analysing":
      return (
        <g data-part="effects">
          <rect x="132" y="120" width="52" height="64" rx="8" fill="#fff" stroke={accent} strokeWidth="3" />
          <line x1="142" y1="136" x2="174" y2="136" stroke={accent} strokeWidth="3" strokeLinecap="round" />
          <line x1="142" y1="148" x2="168" y2="148" stroke={LINE} strokeWidth="3" strokeLinecap="round" />
          <line x1="142" y1="160" x2="172" y2="160" stroke={LINE} strokeWidth="3" strokeLinecap="round" />
          <g className="sv-scan">
            <circle cx="170" cy="168" r="9" fill="none" stroke={accent} strokeWidth="3" />
            <line x1="176" y1="175" x2="184" y2="183" stroke={accent} strokeWidth="3.5" strokeLinecap="round" />
          </g>
        </g>
      );
    case "coaching":
      return (
        <g data-part="effects">
          <g className="sv-bob">
            <path
              d="M140 22 H186 A10 10 0 0 1 196 32 V54 A10 10 0 0 1 186 64 H160 L150 74 L151 64 H140 A10 10 0 0 1 130 54 V32 A10 10 0 0 1 140 22 Z"
              fill={accent}
            />
            <path
              className="sv-box sv-twinkle"
              d="M163 32 L166 40 L174 43 L166 46 L163 54 L160 46 L152 43 L160 40 Z"
              fill="#fff"
            />
          </g>
        </g>
      );
    case "interviewing":
      return (
        <g data-part="effects">
          <rect x="138" y="128" width="44" height="54" rx="6" fill="#fff" stroke={accent} strokeWidth="3" />
          <rect x="150" y="122" width="20" height="10" rx="3" fill={accent} />
          <line x1="146" y1="146" x2="174" y2="146" stroke={LINE} strokeWidth="3" strokeLinecap="round" />
          <line x1="146" y1="158" x2="170" y2="158" stroke={LINE} strokeWidth="3" strokeLinecap="round" />
          <path
            className="sv-check"
            d="M146 170 L152 175 L162 165"
            stroke={accent}
            strokeWidth="3"
            strokeLinejoin="round"
            {...round}
          />
        </g>
      );
    case "speaking":
      return (
        <g data-part="effects">
          <path className="sv-wave" d="M150 100 Q158 112 150 124" stroke={accent} strokeWidth="4" {...round} />
          <path className="sv-wave sv-d2" d="M162 92 Q176 112 162 132" stroke={accent} strokeWidth="4" {...round} />
          <path className="sv-wave sv-d3" d="M174 84 Q194 112 174 140" stroke={accent} strokeWidth="4" {...round} />
        </g>
      );
    case "listening":
      return (
        <g data-part="effects">
          <path className="sv-wave sv-d2" d="M42 86 Q34 98 42 110" stroke={accent} strokeWidth="4" {...round} />
          <path className="sv-wave" d="M30 78 Q18 98 30 118" stroke={accent} strokeWidth="4" {...round} />
        </g>
      );
    case "celebrating":
      return (
        <g data-part="effects">
          <path
            className="sv-box sv-twinkle"
            d="M36 40 L40 50 L50 54 L40 58 L36 68 L32 58 L22 54 L32 50 Z"
            fill={STROVA_COLORS.celebrating.accent}
          />
          <path
            className="sv-box sv-twinkle sv-d2"
            d="M164 30 L167 38 L175 41 L167 44 L164 52 L161 44 L153 41 L161 38 Z"
            fill={accent}
          />
          <circle className="sv-box sv-float" cx="170" cy="74" r="4" fill="#a34d00" />
          <circle className="sv-box sv-float sv-d3" cx="30" cy="84" r="4" fill={accent} />
        </g>
      );
  }
}

export interface StrovaProps {
  mode: StrovaMode;
  /** Width and height in px. */
  size: number;
  /**
   * The hat sets the colour. Defaults: interviewer for listening, speaking and interviewing,
   * coach otherwise. Pass it for thinking: teal in the live room, violet when crafting.
   * Celebrating is always green.
   */
  hat?: StrovaHat;
  className?: string;
}

export function Strova({ mode, size, hat, className }: StrovaProps) {
  // useId output has characters that are awkward inside url(#...); keep letters and digits.
  const clipId = `strova-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const wornHat: StrovaHat = hat ?? (INTERVIEWER_MODES.has(mode) ? "interviewer" : "coach");
  const { accent, soft } = mode === "celebrating" ? STROVA_COLORS.celebrating : STROVA_COLORS[wornHat];
  const effects = size >= STROVA_EFFECTS_MIN_SIZE;

  const up = mode === "thinking";
  const down = mode === "analysing";
  const browUp = mode === "thinking" || mode === "celebrating";
  const eyeL = up ? 88 : down ? 85 : 86;
  const eyeR = up ? 116 : down ? 113 : 114;
  const eyeY = up ? 92 : down ? 99 : 96;
  const eyeRy = mode === "coaching" || mode === "celebrating" ? 4.4 : 5;
  const browL = browUp ? "M79 82 Q86 77 93 81" : mode === "interviewing" ? "M78 84 L94 83" : "M78 83 Q86 79 94 82";
  const browR = browUp
    ? "M107 81 Q114 76 121 82"
    : mode === "interviewing"
      ? "M106 83 L122 84"
      : "M106 82 Q114 79 122 83";
  const zigzag = mode === "thinking" || mode === "analysing";
  const pulse = mode === "celebrating" || mode === "speaking";

  return (
    <svg
      role="img"
      aria-label={STROVA_LABELS[mode]}
      width={size}
      height={size}
      viewBox="0 0 200 200"
      style={{ flex: "none" }}
      className={className ? `strova ${className}` : "strova"}
      data-mode={mode}
      data-hat={mode === "celebrating" ? "celebrating" : wornHat}
    >
      <circle cx="100" cy="100" r="96" fill={soft} />
      {zigzag ? (
        <path
          data-part="ring"
          className="sv-spin"
          d={ZIGZAG_PATH}
          fill="none"
          stroke={accent}
          strokeWidth="4"
          strokeLinejoin="round"
        />
      ) : (
        <circle
          data-part="ring"
          className={pulse ? "sv-pulse-ring" : undefined}
          cx="100"
          cy="100"
          r="93"
          fill="none"
          stroke={accent}
          strokeWidth="6"
        />
      )}
      <defs>
        <clipPath id={clipId}>
          <circle cx="100" cy="100" r="93" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <path d="M28 205 C28 162 60 144 100 144 C140 144 172 162 172 205 Z" fill={TOP} />
        <path d="M84 145 L100 170 L116 145 Z" fill={SHADE} />
        <path d="M78 147 L100 176 L90 186 Z" fill="rgba(23,22,31,0.12)" />
        <path d="M122 147 L100 176 L110 186 Z" fill="rgba(23,22,31,0.12)" />
        <g transform={HEAD_TRANSFORM} fill={HAIR}>
          {HAIR_BACK.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>
        <rect x="88" y="118" width="24" height="32" rx="10" fill={SHADE} />
        <path transform={HEAD_TRANSFORM} fill={SKIN} d={FACE} />
        <g transform={HEAD_TRANSFORM} fill={HAIR}>
          {HAIR_FRONT.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>
        <path d={browL} stroke={HAIR} strokeWidth="3.5" {...round} />
        <path d={browR} stroke={HAIR} strokeWidth="3.5" {...round} />
        <ellipse className="sv-box sv-blink" cx={eyeL} cy={eyeY} rx="4.2" ry={eyeRy} fill="#1f1a24" />
        <ellipse className="sv-box sv-blink" cx={eyeR} cy={eyeY} rx="4.2" ry={eyeRy} fill="#1f1a24" />
        {mode === "speaking" ? (
          <ellipse data-part="mouth" className="sv-box sv-talk" cx="100" cy="116" rx="7" ry="5" fill="#7a2e2e" />
        ) : (
          <path data-part="mouth" d={MOUTHS[mode]} stroke="#9a3b3b" strokeWidth="3" {...round} />
        )}
      </g>
      {effects && <Effects mode={mode} accent={accent} />}
    </svg>
  );
}
