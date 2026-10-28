import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import type { StandardType } from "../../api/types";
import { competencyLabel, interviewTypeLabel } from "../../labels";
import type { Competency } from "./api";

/** The competency list, grouped by the interview type that scores it. */
const GROUPS = Object.entries(COMPETENCIES_BY_TYPE) as [StandardType, Competency[]][];

/** ST-3: the story's skill tags, picked from the competency list. Toggle buttons, so the state is spoken. */
export function SkillPicker({ value, onChange }: { value: Competency[]; onChange: (next: Competency[]) => void }) {
  const toggle = (c: Competency) => onChange(value.includes(c) ? value.filter((v) => v !== c) : [...value, c]);
  return (
    <fieldset className="story-skills">
      <legend className="label">Skills this story proves</legend>
      {GROUPS.map(([type, comps]) => (
        <div key={type} className="story-skills__group" role="group" aria-label={interviewTypeLabel[type]}>
          <p className="muted small">{interviewTypeLabel[type]}</p>
          <div className="chip-list">
            {comps.map((c) => (
              <button
                key={c}
                type="button"
                className="chip chip--toggle"
                aria-pressed={value.includes(c)}
                onClick={() => toggle(c)}
              >
                {competencyLabel(c)}
              </button>
            ))}
          </div>
        </div>
      ))}
    </fieldset>
  );
}
