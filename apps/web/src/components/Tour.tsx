/**
 * R3 explainability: a 3-step tour, once, on the first visit: the menu, Career Stories with Strova
 * and the top bar. Each step outlines its part of the page and says what it is for. Skip or finish,
 * and it does not come back; "Replay the tour" on the How it works page starts it again. Remembered
 * per user in this browser. The tour is a small non-modal card, so the page stays usable.
 */
import { useEffect, useState } from "react";

const doneKey = (userId: string) => `sh-tour-done-${userId}`;
/** Sent by the How it works page to start the tour again. */
export const TOUR_REPLAY_EVENT = "sh-tour-replay";

const STEPS = [
  {
    target: "menu",
    title: "Your menu",
    text: "Your resumes, your target roles and your Career Stories are what you build. Rehearse each interview with Strova, who plays the interviewer.",
  },
  {
    target: "coach",
    title: "Career Stories with Strova",
    text: "Strova helps you turn your career into stories, by voice or by typing. Open it any time from here.",
  },
  {
    target: "topbar",
    title: "Your top bar",
    text: "Your plan and what's left of it, and your profile and account. Help and how it works is in the account menu.",
  },
] as const;

const seen = (userId: string) => {
  try {
    return globalThis.localStorage?.getItem(doneKey(userId)) !== null;
  } catch {
    return true; // without storage the tour cannot be remembered, so do not show it on every page
  }
};

/** The element a step points at: the first of its targets that is on screen. */
function targetOf(name: string): HTMLElement | null {
  const all = [...document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)];
  return all.find((el) => el.offsetParent !== null) ?? null;
}

export function Tour({ userId }: { userId: string }) {
  const [step, setStep] = useState<number | null>(() => (seen(userId) ? null : 0));

  useEffect(() => {
    const replay = () => setStep(0);
    window.addEventListener(TOUR_REPLAY_EVENT, replay);
    return () => window.removeEventListener(TOUR_REPLAY_EVENT, replay);
  }, []);

  // Outline the part of the page this step is about.
  useEffect(() => {
    if (step === null) return;
    const el = targetOf(STEPS[step].target);
    el?.setAttribute("data-tour-active", "true");
    return () => el?.removeAttribute("data-tour-active");
  }, [step]);

  if (step === null) return null;
  const finish = () => {
    try {
      globalThis.localStorage?.setItem(doneKey(userId), new Date().toISOString());
    } catch {
      /* not remembered: harmless */
    }
    setStep(null);
  };
  const s = STEPS[step];
  const last = step === STEPS.length - 1;
  return (
    <section className="tour" role="dialog" aria-labelledby="tour-title" aria-describedby="tour-text">
      <p className="tour__count">
        {step + 1} of {STEPS.length}
      </p>
      <h2 id="tour-title">{s.title}</h2>
      <p id="tour-text">{s.text}</p>
      <div className="tour__actions">
        <button type="button" className="btn btn--quiet" onClick={finish}>
          Skip the tour
        </button>
        <button type="button" className="btn" onClick={() => (last ? finish() : setStep(step + 1))}>
          {last ? "Done" : "Next tip"}
        </button>
      </div>
    </section>
  );
}
