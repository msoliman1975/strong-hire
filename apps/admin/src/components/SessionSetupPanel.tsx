/**
 * AD-5, RS-2: the brief prompt (planner) and the rubric prompt (scorer) for the session's type, on
 * the session and replay pages. Prompt files only: a user's own brief is never shown in admin
 * (AA-11, D-8).
 */
import type { AdminPrompt, AdminSessionSetup } from "../api/part3";

function PromptBlock({ label, prompt, recordedNote }: { label: string; prompt: AdminPrompt | null | undefined; recordedNote: string }) {
  if (!prompt) return <p className="muted">No {label.toLowerCase()} found.</p>;
  return (
    <details className="panel">
      <summary>
        {label} <code>{prompt.ref}</code> {prompt.recorded ? `(${recordedNote})` : "(current version for this type)"}
      </summary>
      {prompt.text ? <pre className="json-view">{prompt.text}</pre> : <p>The prompt file is no longer in the repo.</p>}
    </details>
  );
}

export function SessionSetupPanel({ setup }: { setup: AdminSessionSetup | null | undefined }) {
  if (!setup) return null;
  return (
    <section className="section" aria-labelledby="session-setup">
      <h2 id="session-setup">Brief and rubric prompts</h2>
      <p className="muted">The prompts for this interview type. The user&apos;s own brief is never shown here.</p>
      <PromptBlock label="Brief prompt" prompt={setup.brief_prompt} recordedNote="used for this interview" />
      <PromptBlock label="Rubric" prompt={setup.rubric} recordedNote="used for this scorecard" />
    </section>
  );
}
