import { useState } from "react";

import { COMPETENCIES_BY_TYPE } from "../../api/questions";
import type { StandardType } from "../../api/types";
import { competencyLabel, interviewTypeLabel } from "../../labels";
import type { Competency } from "./api";

/**
 * The competency list, grouped by the interview type that scores it. Each skill shows once, in
 * the first group that has it: the recruiter screen repeats Motivation, Role fit and Communication.
 */
const GROUPS: [StandardType, Competency[]][] = (() => {
  const seen = new Set<Competency>();
  return (Object.entries(COMPETENCIES_BY_TYPE) as [StandardType, Competency[]][])
    .map(([type, comps]): [StandardType, Competency[]] => [type, comps.filter((c) => !seen.has(c) && seen.add(c))])
    .filter(([, comps]) => comps.length > 0);
})();

/** Stories answer behavioral questions, so that group always shows. */
const ALWAYS: StandardType = "behavioral";

/**
 * ST-3: the story's skill tags, picked from the competency list. Toggle buttons, so the state is
 * spoken. Only the groups the story uses (and Behavioral) show; "Show all skills" opens the rest.
 */
export function SkillPicker({ value, onChange }: { value: Competency[]; onChange: (next: Competency[]) => void }) {
  const [all, setAll] = useState(false);
  const toggle = (c: Competency) => onChange(value.includes(c) ? value.filter((v) => v !== c) : [...value, c]);
  // Groups open when the picker mounts stay open, so a skill does not vanish when it is unticked.
  const [open] = useState(() => new Set(GROUPS.filter(([t, comps]) => t === ALWAYS || comps.some((c) => value.includes(c))).map(([t]) => t)));
  const shown = all ? GROUPS : GROUPS.filter(([t]) => open.has(t));
  const hidden = GROUPS.length - shown.length;
  return (
    <fieldset className="story-skills">
      <legend className="label">Skills this story proves</legend>
      {shown.map(([type, comps]) => (
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
      {hidden > 0 && (
        <button className="btn btn--quiet story-skills__more" type="button" onClick={() => setAll(true)}>
          Show all skills ({hidden} more {hidden === 1 ? "group" : "groups"})
        </button>
      )}
    </fieldset>
  );
}
