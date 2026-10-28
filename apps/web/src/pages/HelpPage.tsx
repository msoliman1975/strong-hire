/**
 * R3 explainability: "How it works", from the avatar menu (Help and how it works). One page: the
 * two journeys, how scoring works, Coach and Realistic modes, and what we keep. It states only
 * what the app does today, and offers to replay the 3-step tour.
 */
import { Link, useNavigate } from "react-router";

import { TOUR_REPLAY_EVENT } from "../components/Tour";
import { PageHead } from "../components/ui";
import { MAX_RESUME_MB, MAX_RESUMES } from "../limits";
import { READINESS_NOTICE } from "./plan/ReadinessApi";

export function HelpPage() {
  const navigate = useNavigate();
  return (
    <div className="help-page page--narrow stack">
      <PageHead title="How it works">
        <p>Strong Hire helps you get ready for a real interview: you build your stories, then you rehearse with an AI interviewer and get a debrief.</p>
        <div>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => {
              navigate("/");
              // The shell's tour listens for this, once Home is on screen.
              window.setTimeout(() => window.dispatchEvent(new Event(TOUR_REPLAY_EVENT)), 0);
            }}
          >
            Replay the tour
          </button>
        </div>
      </PageHead>

      <section className="card stack" aria-labelledby="help-journeys">
        <h2 id="help-journeys">Two ways in</h2>
        <h3>Build your stories</h3>
        <p>
          A story is one moment from your career, told in five parts: context, stakes, your action, the result and what
          you learned. Your coach asks questions and fills the parts from your own words. Then you practice it in
          takes, typed or spoken, and each take is scored on the story's skills from 1 to 4.
        </p>
        <h3>Prep for an interview</h3>
        <p>
          Add the job description and your resume. We compare them for a match score and a plan: what they'll test,
          where they'll probe, which of your stories fits each skill, and the next rehearsal. A rehearsal is a mock
          interview with an AI interviewer, by voice or by text, followed by a debrief.
        </p>
        <p>
          <Link to="/jobs">Go to your interviews</Link> · <Link to="/stories">Go to your stories</Link>
        </p>
      </section>

      <section className="card stack" aria-labelledby="help-modes">
        <h2 id="help-modes">Coach mode and Realistic mode</h2>
        <p>
          <b>Coach mode</b> lets you pause, ask for a hint, or redo an answer. It does not count toward your progress.
        </p>
        <p>
          <b>Realistic mode</b> runs like a real interview, with no interruptions. Only Realistic rehearsals count
          toward practice readiness, and a story turns Proven when a Realistic answer that uses it meets the bar.
        </p>
      </section>

      <section className="card stack" aria-labelledby="help-scoring">
        <h2 id="help-scoring">How scoring works</h2>
        <p>
          Each answer is scored on the skills the interview tests, from 1 to 4. A 3 or more meets the bar. The debrief
          shows how many answers met the bar, a hire signal from No Hire to Strong Hire, and one fix for each answer.
        </p>
        <p className="muted">{READINESS_NOTICE}</p>
      </section>

      <section className="card stack" aria-labelledby="help-keep">
        <h2 id="help-keep">What we keep</h2>
        <p>
          Your audio is never stored. We keep the text of your rehearsals and coach sessions, your stories, and up to{" "}
          {MAX_RESUMES} resumes (files up to {MAX_RESUME_MB} MB each). You can export everything, or delete your account,
          from <Link to="/account">Account</Link>.
        </p>
      </section>
    </div>
  );
}
