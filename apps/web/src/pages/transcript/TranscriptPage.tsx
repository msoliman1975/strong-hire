import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { ErrorNotice, Loading, PageHead } from "../../components/ui";
import { formatDate, phaseLabel } from "../../labels";
import { useTranscript, type TranscriptGroup, type TranscriptTurn } from "./api";
import "./transcript.css";

/**
 * TR-1: what the candidate and the interviewer said in a finished session, in order, grouped by
 * question, with each turn's time from the start. Text only: audio is never kept.
 */
export function TranscriptPage() {
  const { sessionId = "" } = useParams();
  const transcript = useTranscript(sessionId);
  const debriefPath = `/sessions/${sessionId}/debrief`;

  if (transcript.isPending) return <Loading label="Loading the transcript" />;
  if (transcript.isError) {
    const err = transcript.error;
    const notEnded = err instanceof ApiError && err.status === 409;
    const notFound = err instanceof ApiError && err.status === 404;
    return (
      <>
        <Breadcrumb debriefPath={debriefPath} />
        <PageHead title="Transcript" />
        {notEnded ? (
          <section className="section panel" data-testid="transcript-not-ended">
            <p>This interview has not finished. The transcript is ready when it ends.</p>
          </section>
        ) : notFound ? (
          <ErrorNotice error="We could not find this interview." />
        ) : (
          <ErrorNotice error={err} />
        )}
      </>
    );
  }

  const { groups, started_at, ended_at } = transcript.data;
  const turns = groups.reduce((n, g) => n + g.turns.length, 0);
  const numbers = questionNumbers(groups);

  return (
    <>
      <Breadcrumb debriefPath={debriefPath} />
      <PageHead title="Transcript" eyebrow="Debrief · Transcript" eyebrowTone="muted">
        <p>
          {formatDate(started_at ?? ended_at)}. What you and the interviewer said, in order. We keep the text only; the
          audio is never stored.
        </p>
      </PageHead>
      <p>
        <Link to={debriefPath}>Back to the debrief</Link>
      </p>
      {turns === 0 ? (
        <section className="section panel" data-testid="transcript-empty">
          <p>Nothing was said in this interview, so there is no transcript.</p>
        </section>
      ) : (
        <ol className="transcript" aria-label="Transcript">
          {groups.map((group) => (
            <Group
              key={group.turns[0].id}
              group={group}
              number={group.question_ref ? (numbers.get(group.question_ref) ?? null) : null}
            />
          ))}
        </ol>
      )}
    </>
  );
}

/** Questions are numbered in the order they were first asked. */
function questionNumbers(groups: TranscriptGroup[]): Map<string, number> {
  const numbers = new Map<string, number>();
  for (const g of groups) if (g.question_ref && !numbers.has(g.question_ref)) numbers.set(g.question_ref, numbers.size + 1);
  return numbers;
}

function Group({ group, number }: { group: TranscriptGroup; number: number | null }) {
  const heading = number !== null ? `Question ${number}` : phaseLabel[group.phase];
  return (
    <li className="transcript__group">
      <h2 className="transcript__heading">
        {heading}
        {group.question_text && <span className="transcript__question">{group.question_text}</span>}
      </h2>
      <ol className="transcript__turns">
        {group.turns.map((turn) => (
          <Turn key={turn.id} turn={turn} />
        ))}
      </ol>
    </li>
  );
}

function Turn({ turn }: { turn: TranscriptTurn }) {
  const who = turn.speaker === "candidate" ? "You" : "Interviewer";
  return (
    <li className="transcript__turn" data-speaker={turn.speaker}>
      <p className="transcript__meta">
        <span className="transcript__speaker">{who}</span>
        <time className="transcript__time">{offset(turn.start_ms)}</time>
      </p>
      <p className="transcript__text">{turn.text}</p>
    </li>
  );
}

/** "m:ss" from the session start; "h:mm:ss" past an hour. */
export function offset(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const s = String(total % 60).padStart(2, "0");
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function Breadcrumb({ debriefPath }: { debriefPath: string }) {
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        <li>
          <Link to="/">Interview rehearsals</Link>
        </li>
        <li>
          <Link to={debriefPath}>Debrief</Link>
        </li>
        <li aria-current="page">Transcript</li>
      </ol>
    </nav>
  );
}
