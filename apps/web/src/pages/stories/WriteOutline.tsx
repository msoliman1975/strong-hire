/**
 * SC-1, SC-10 (Write it yourself in STAR or CARL): the outline's sections as fields the user fills
 * in their own words. The required slots (D-4) and the context slots (D-5) show first; each
 * section's other slots sit under "More, if you have them". Action has numbered steps (1 to 5).
 * Every field takes light Markdown (SC-18). Nothing here calls a model: the text is saved as typed.
 */
import { useRef, type ReactNode } from "react";

import { markdownKeys, MarkdownToolbar } from "../../components/markdown/markdown";
import {
  CONTEXT_SLOTS,
  CORE_SLOTS,
  SECTION_LABEL,
  SECTION_SLOTS,
  SLOT_LABEL,
  STEP_FIELDS,
  STYLE_SECTIONS,
  type StorySection,
  type StoryStyle,
} from "../coach/outline";
import type { SlotEditIn } from "./api";

export const MAX_STEPS = 5;

/** The typed text of each slot, keyed `section.slot` or `action.did.0`. */
export type Written = Record<string, string>;

const key = (section: StorySection, slot: string, step: number | null) =>
  step === null ? `${section}.${slot}` : `${section}.${slot}.${step}`;

/** The filled fields as the API's slot edits. */
export function writtenSlots(style: StoryStyle, values: Written, steps: number): SlotEditIn[] {
  const out: SlotEditIn[] = [];
  for (const section of STYLE_SECTIONS[style]) {
    if (section === "action") {
      for (let i = 0; i < steps; i++) {
        for (const slot of STEP_FIELDS) {
          const text = values[key(section, slot, i)]?.trim();
          if (text) out.push({ section, slot, step: i, text, skipped: false });
        }
      }
      continue;
    }
    for (const slot of SECTION_SLOTS[style][section] ?? []) {
      const text = values[key(section, slot, null)]?.trim();
      if (!text) continue;
      const edit: SlotEditIn = { section, slot, step: null, text, skipped: false };
      if (slot === "metric") {
        edit.before = values[`${section}.metric.before`]?.trim() || null;
        edit.after = values[`${section}.metric.after`]?.trim() || null;
      }
      out.push(edit);
    }
  }
  return out;
}

function Field({
  id,
  label,
  required,
  value,
  onChange,
  children,
}: {
  id: string;
  label: string;
  required: boolean;
  value: string;
  onChange: (v: string) => void;
  children?: ReactNode;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const keys = markdownKeys(onChange);
  return (
    <div className="sx-field write-slot" data-required={required || undefined}>
      <label htmlFor={id} className="write-slot__label">
        {label}
        {required && <span className="write-slot__need"> · needed for Ready</span>}
      </label>
      <MarkdownToolbar target={area} onChange={onChange} label={`Format ${label}`} />
      <textarea
        id={id}
        ref={area}
        rows={2}
        maxLength={8000}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          keys.onKeyDown(e);
        }}
        onPaste={keys.onPaste}
      />
      {children}
    </div>
  );
}

export function WriteOutline({
  style,
  values,
  onChange,
  steps,
  onSteps,
}: {
  style: StoryStyle;
  values: Written;
  onChange: (next: Written) => void;
  steps: number;
  onSteps: (n: number) => void;
}) {
  const set = (k: string) => (v: string) => onChange({ ...values, [k]: v });
  const field = (section: StorySection, slot: string, step: number | null) => {
    const k = key(section, slot, step);
    const label = `${step !== null ? `Step ${step + 1}: ` : ""}${SLOT_LABEL[slot] ?? slot}`;
    return (
      <Field
        key={k}
        id={`write-${k.replace(/\./g, "-")}`}
        label={label}
        required={CORE_SLOTS.has(slot)}
        value={values[k] ?? ""}
        onChange={set(k)}
      >
        {slot === "metric" && (
          <div className="sx-row write-slot__numbers">
            <label>
              Before
              <input value={values[`${section}.metric.before`] ?? ""} maxLength={100} onChange={(e) => set(`${section}.metric.before`)(e.target.value)} />
            </label>
            <label>
              After
              <input value={values[`${section}.metric.after`] ?? ""} maxLength={100} onChange={(e) => set(`${section}.metric.after`)(e.target.value)} />
            </label>
          </div>
        )}
      </Field>
    );
  };

  return (
    <div className="write-outline" data-testid="write-outline">
      {STYLE_SECTIONS[style].map((section) => {
        const slots = SECTION_SLOTS[style][section] ?? [];
        const main = slots.filter((s) => CORE_SLOTS.has(s) || CONTEXT_SLOTS.has(s));
        const more = slots.filter((s) => !main.includes(s));
        return (
          <fieldset key={section} className="write-section" data-section={section}>
            <legend className="write-section__legend">{SECTION_LABEL[section]}</legend>
            {section === "action" ? (
              <>
                {Array.from({ length: steps }, (_, i) => (
                  <div key={i} className="write-step" role="group" aria-label={`Step ${i + 1}`}>
                    {field(section, "did", i)}
                    {field(section, "why", i)}
                    <details className="write-more">
                      <summary>More for step {i + 1}, if you have it</summary>
                      {field(section, "alternatives", i)}
                      {field(section, "people", i)}
                    </details>
                  </div>
                ))}
                <div className="sx-row">
                  {steps < MAX_STEPS && (
                    <button type="button" className="sx-btn ghost sm" onClick={() => onSteps(steps + 1)}>
                      Add a step
                    </button>
                  )}
                  {steps > 1 && (
                    <button
                      type="button"
                      className="sx-btn quiet sm"
                      onClick={() => {
                        const next = { ...values };
                        for (const slot of STEP_FIELDS) delete next[key("action", slot, steps - 1)];
                        onChange(next);
                        onSteps(steps - 1);
                      }}
                    >
                      Remove step {steps}
                    </button>
                  )}
                </div>
              </>
            ) : (
              <>
                {main.map((slot) => field(section, slot, null))}
                {more.length > 0 &&
                  (main.length === 0 ? (
                    more.map((slot) => field(section, slot, null))
                  ) : (
                    <details className="write-more">
                      <summary>More, if you have them</summary>
                      {more.map((slot) => field(section, slot, null))}
                    </details>
                  ))}
              </>
            )}
          </fieldset>
        );
      })}
    </div>
  );
}
