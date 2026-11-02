/**
 * SC-7 (UI): the outline of a styled story, live beside the conversation. Each section lists its
 * slots as chips that say their state in text (Filled, Empty, Skipped), the section in progress
 * is highlighted, and the slots Strova is asking about are marked. Ready shows when the core
 * slots are filled (SC-3).
 */
import { Markdown } from "../../components/markdown/markdown";
import { Strova } from "../../components/strova";
import {
  CONTEXT_SLOTS,
  CORE_SLOTS,
  SECTION_LABEL,
  SLOT_LABEL,
  STATUS_TEXT,
  STYLE_NAME,
  isFilled,
  outlineReady,
  sectionSlots,
  refId,
  viewId,
  type CraftAsk,
  type SlotView,
  type StoryOutline,
} from "./outline";

/** Optional slots that are empty are listed in one quiet line, so the panel stays short. */
function SlotChip({ view, asking }: { view: SlotView; asking: boolean }) {
  const { slot, key } = view;
  const core = CORE_SLOTS.has(key);
  const state = slot.status;
  return (
    <li
      className="craft-slot"
      data-state={state}
      data-asking={asking || undefined}
      data-testid="craft-slot"
      data-slot={viewId(view)}
    >
      <p className="craft-slot__label">
        <span className="craft-slot__name">
          {view.step !== null ? `Step ${view.step + 1}: ` : ""}
          {SLOT_LABEL[key] ?? key}
        </span>
        <span className="craft-slot__state">
          {asking ? "Strova is asking" : STATUS_TEXT[state]}
          {core && state !== "filled" ? " · needed for Ready" : ""}
        </span>
      </p>
      {isFilled(slot) && <Markdown className="craft-slot__text" text={slot.text ?? ""} />}
    </li>
  );
}

export function CraftPanel({
  outline,
  asking,
  ended,
}: {
  outline: StoryOutline;
  asking: CraftAsk | null | undefined;
  ended: boolean;
}) {
  const ready = outlineReady(outline);
  // Strova asks one thing at a time: the first empty slot she was given.
  const askingIds = new Set((asking?.slots ?? []).slice(0, 1).map(refId));
  const current = ended ? null : (asking?.section ?? null);
  return (
    <div className="craft-panel" data-testid="craft-panel">
      <div className="coach__strova" data-testid="coach-strova">
        <Strova mode={ready ? "celebrating" : "thinking"} size={72} hat="coach" />
        <span className="muted small">
          {ready
            ? "Every core slot is filled. Strova saved your story as Ready."
            : "Strova fills each slot from your words, one section at a time."}
        </span>
      </div>
      <p className="muted small craft-panel__style">
        {STYLE_NAME[outline.style]} story{ready ? " · Ready" : ""}
      </p>
      <ol className="plain-list craft-panel__sections" aria-label="Story sections">
        {outline.sections.map((section) => {
          const views = sectionSlots(outline, section);
          const now = current === section.section;
          const shown = views.filter(
            (v) =>
              v.slot.status !== "empty" || CORE_SLOTS.has(v.key) || CONTEXT_SLOTS.has(v.key) || askingIds.has(viewId(v)),
          );
          const quiet = views.filter((v) => !shown.includes(v));
          const filledCount = views.filter((v) => v.slot.status === "filled").length;
          return (
            <li
              key={section.section}
              className="craft-section"
              data-current={now || undefined}
              data-testid="craft-section"
              data-section={section.section}
            >
              <h3 className="craft-section__head">
                <span>{SECTION_LABEL[section.section]}</span>
                <span className="craft-section__state">
                  {now ? "In progress" : `${filledCount} filled`}
                </span>
              </h3>
              <ul className="plain-list craft-section__slots">
                {shown.map((v) => (
                  <SlotChip
                    key={viewId(v)}
                    view={v}
                    asking={!ended && askingIds.has(viewId(v))}
                  />
                ))}
              </ul>
              {quiet.length > 0 && (
                <p className="muted small craft-section__more">
                  Also, if you have them: {[...new Set(quiet.map((v) => SLOT_LABEL[v.key] ?? v.key))].join(", ")}
                </p>
              )}
            </li>
          );
        })}
      </ol>
      <p className="muted small">
        Say “skip” for a slot you can’t share, or “move on” to go to the next section.
      </p>
    </div>
  );
}
