import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { adminDownloads } from "../api/admin";
import {
  latencyLevel,
  lineAt,
  splitTimes,
  useReplay,
  type ReplayJudge,
  type ReplayLine,
  type ReplayScorecard,
  type SessionReplay,
} from "../api/sim";
import { ErrorNotice, Loading, PageHead } from "../components/ui";
import { clock, words } from "../format";
import { phaseLabel } from "../labels";
import type { Phase } from "../api/types";

const SKIP_MS = 10_000;
const SPEEDS = [1, 1.25, 1.5, 2];

type Seek = (ms: number, play?: boolean) => void;
type ChannelMode = "mixed" | "stereo";

/** The keys below are ignored while the admin types in a field or uses a control. */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName) || target.isContentEditable;
}

/**
 * SM-7 "Mixed" or "Stereo" through Web Audio: four gains route each channel of the recording to
 * each ear. The graph is built on the first play (a user gesture), once per audio element.
 */
interface Graph {
  ctx: AudioContext;
  gains: { ll: GainNode; rr: GainNode; lr: GainNode; rl: GainNode };
}

function audioContextClass(): typeof AudioContext | undefined {
  return (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;
}

function buildGraph(audio: HTMLAudioElement): Graph | null {
  const Ctx = audioContextClass();
  if (!Ctx) return null;
  const ctx = new Ctx();
  const source = ctx.createMediaElementSource(audio);
  const split = ctx.createChannelSplitter(2);
  const merge = ctx.createChannelMerger(2);
  source.connect(split);
  const gain = (from: number, to: number) => {
    const g = ctx.createGain();
    split.connect(g, from);
    g.connect(merge, 0, to);
    return g;
  };
  const gains = { ll: gain(0, 0), rr: gain(1, 1), lr: gain(0, 1), rl: gain(1, 0) };
  merge.connect(ctx.destination);
  return { ctx, gains };
}

function applyMode(graph: Graph, mode: ChannelMode) {
  const { ll, rr, lr, rl } = graph.gains;
  const same = mode === "mixed" ? 0.5 : 1;
  const cross = mode === "mixed" ? 0.5 : 0;
  ll.gain.value = same;
  rr.gain.value = same;
  lr.gain.value = cross;
  rl.gain.value = cross;
}

function LatencyChip({ ms, okMs, slowMs }: { ms: number; okMs: number; slowMs: number }) {
  const level = latencyLevel(ms, okMs, slowMs);
  return (
    <span className="latency" data-level={level} title="Interviewer response time">
      <span className="sr-only">Response time </span>
      {(ms / 1000).toFixed(1)} s
    </span>
  );
}

/** SM-10: every mm:ss in judge text seeks the player. */
function WithTimes({ text, seek }: { text: string; seek: Seek }) {
  return (
    <>
      {splitTimes(text).map((part, i) =>
        typeof part === "string" ? (
          <span key={i}>{part}</span>
        ) : (
          <button key={i} type="button" className="btn--link time-link" onClick={() => seek(part.ms, true)}>
            {part.text}
          </button>
        ),
      )}
    </>
  );
}

interface Marker {
  ms: number;
  kind: "slow" | "problem";
  label: string;
}

/** SM-7: play/pause, back/forward 10 s, speed, scrubber with markers, Mixed or Stereo. */
function Player({
  audioRef,
  sessionId,
  current,
  durationMs,
  playing,
  markers,
  seek,
  toggle,
  mode,
  setMode,
}: {
  audioRef: React.RefObject<HTMLAudioElement | null>;
  sessionId: string;
  current: number;
  durationMs: number;
  playing: boolean;
  markers: Marker[];
  seek: Seek;
  toggle: () => void;
  mode: ChannelMode;
  setMode: (m: ChannelMode) => void;
}) {
  const [speed, setSpeed] = useState(1);
  const webAudio = audioContextClass() !== undefined;
  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [audioRef, speed]);
  const total = Math.max(durationMs, current, 1);

  return (
    <section className="panel section player" aria-label="Player">
      <audio ref={audioRef} src={adminDownloads.audio(sessionId)} preload="metadata" />
      <div className="row player__controls">
        <button type="button" className="btn" onClick={() => seek(current - SKIP_MS)} aria-label="Back 10 seconds">
          −10 s
        </button>
        <button type="button" className="btn btn--primary" onClick={toggle}>
          {playing ? "Pause" : "Play"}
        </button>
        <button type="button" className="btn" onClick={() => seek(current + SKIP_MS)} aria-label="Forward 10 seconds">
          +10 s
        </button>
        <span className="mono-small" aria-live="off">
          {clock(current)} / {clock(durationMs || null)}
        </span>
        <div className="segmented" role="group" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button key={s} type="button" className="btn btn--small" aria-pressed={speed === s} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Channels">
          <button
            type="button"
            className="btn btn--small"
            aria-pressed={mode === "mixed"}
            disabled={!webAudio}
            onClick={() => setMode("mixed")}
          >
            Mixed
          </button>
          <button
            type="button"
            className="btn btn--small"
            aria-pressed={mode === "stereo"}
            disabled={!webAudio}
            onClick={() => setMode("stereo")}
            title="Interviewer left, candidate right"
          >
            Stereo
          </button>
        </div>
      </div>
      <div className="scrubber">
        <input
          type="range"
          aria-label="Position"
          min={0}
          max={total}
          step={100}
          value={Math.min(current, total)}
          onChange={(e) => seek(Number(e.target.value))}
        />
        <div className="scrubber__marks">
          {markers.map((m, i) => (
            <button
              key={i}
              type="button"
              className="scrubber__mark"
              data-kind={m.kind}
              style={{ left: `${(m.ms / total) * 100}%` }}
              aria-label={`${m.label} at ${clock(m.ms)}`}
              title={`${m.label} at ${clock(m.ms)}`}
              onClick={() => seek(m.ms, true)}
            />
          ))}
        </div>
      </div>
      <p className="muted small">
        Keys: space play or pause, ← → 10 s, J K previous or next line, N next slow turn. Markers: slow turns (red) and
        judge problems (amber).
      </p>
    </section>
  );
}

/** SM-8: the line being played is highlighted and kept in view until the admin scrolls. */
function Transcript({
  replay,
  active,
  seek,
  follow,
  setFollow,
}: {
  replay: SessionReplay;
  active: number;
  seek: Seek;
  follow: boolean;
  setFollow: (f: boolean) => void;
}) {
  const items = useRef<(HTMLLIElement | null)[]>([]);
  useEffect(() => {
    if (follow && active >= 0) items.current[active]?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [active, follow]);
  const { ok_ms, slow_ms } = replay.latency;

  return (
    <section className="section" aria-labelledby="replay-transcript">
      <div className="row">
        <h2 id="replay-transcript">Transcript</h2>
        {!follow && (
          <button type="button" className="btn btn--small" onClick={() => setFollow(true)}>
            Follow
          </button>
        )}
      </div>
      {replay.lines.length === 0 ? (
        <p>No transcript.</p>
      ) : (
        <ol
          className="transcript panel replay-transcript"
          onWheel={() => setFollow(false)}
          onTouchMove={() => setFollow(false)}
        >
          {replay.lines.map((line: ReplayLine, i) => (
            <li
              key={i}
              ref={(el) => {
                items.current[i] = el;
              }}
              className={i === active ? "is-current" : undefined}
              aria-current={i === active ? "true" : undefined}
            >
              <button type="button" className="btn--link time-link" onClick={() => seek(line.start_ms, true)}>
                {clock(line.start_ms)}
              </button>{" "}
              {line.speaker === "interviewer" && line.latency_ms !== null && (
                <LatencyChip ms={line.latency_ms} okMs={ok_ms} slowMs={slow_ms} />
              )}{" "}
              <span className="who">{line.speaker === "interviewer" ? "Interviewer" : "Candidate"}</span>
              {line.phase && <span className="muted small"> {phaseLabel[line.phase as Phase] ?? words(line.phase)}</span>}
              {line.note && <span className="tag"> ({line.note})</span>}
              <div>{line.text}</div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function JudgePanel({ judge, seek }: { judge: ReplayJudge | null; seek: Seek }) {
  return (
    <section className="panel section" aria-labelledby="replay-judge">
      <h2 id="replay-judge">Judge</h2>
      {!judge ? (
        <p>Not judged (the run was cancelled or failed before the judge).</p>
      ) : (
        <>
          <p className="muted small">
            {judge.rubric ?? "rubric unknown"} · {judge.model ?? "model unknown"}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">Verdict</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {judge.rules.map((r) => (
                  <tr key={r.rule} data-verdict={r.verdict}>
                    <td>{words(r.rule)}</td>
                    <td>
                      <span className="verdict" data-verdict={r.verdict}>
                        {r.verdict === "not_applicable" ? "n/a" : r.verdict}
                      </span>
                    </td>
                    <td>
                      <WithTimes text={r.reason} seek={seek} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Problems</h3>
          {judge.problems.length === 0 ? (
            <p>None.</p>
          ) : (
            <ul>
              {judge.problems.map((p, i) => (
                <li key={i}>
                  {p.at_ms !== null ? (
                    <button type="button" className="btn--link time-link" onClick={() => seek(p.at_ms ?? 0, true)}>
                      {p.at}
                    </button>
                  ) : (
                    <span className="muted">{p.at}</span>
                  )}{" "}
                  <WithTimes text={p.problem} seek={seek} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function ScorecardPanel({ card }: { card: ReplayScorecard | null }) {
  return (
    <section className="panel section" aria-labelledby="replay-scorecard">
      <h2 id="replay-scorecard">Scorecard</h2>
      {!card ? (
        <p>No scorecard (the interview was not scored).</p>
      ) : (
        <>
          <p>
            <strong>{card.hire_signal}</strong>
          </p>
          <p>{card.rationale}</p>
          <ul className="score-list">
            {card.competency_scores.map((c) => (
              <li key={c.competency}>
                <strong>{words(c.competency)}</strong> {c.score} / 4
                <div>{c.justification}</div>
                {c.quotes.map((q, i) => (
                  <blockquote key={i} className="muted small">
                    “{q}”
                  </blockquote>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Summary({ replay }: { replay: SessionReplay }) {
  const { latency, scenario } = replay;
  const items: ReactNode[] = [];
  if (scenario) {
    items.push(
      `${scenario.persona} · ${words(scenario.interview_type)} · ${scenario.channel} · ${scenario.duration_min} min · ${scenario.quality} · ${words(scenario.behavior)}`,
    );
  }
  return (
    <section className="section" aria-label="Summary">
      {items.map((x, i) => (
        <p key={i}>{x}</p>
      ))}
      <dl className="dl">
        <dt>Response time p50</dt>
        <dd>{latency.p50_ms !== null ? `${latency.p50_ms} ms` : "-"}</dd>
        <dt>Response time p90</dt>
        <dd>{latency.p90_ms !== null ? `${latency.p90_ms} ms` : "-"}</dd>
        <dt>Slow turns (over {latency.slow_ms} ms)</dt>
        <dd>
          {latency.slow_turns} of {latency.n}
        </dd>
      </dl>
    </section>
  );
}

/** Replay (SM-7 to SM-11): audio with a synced transcript, the judge and the scorecard. */
export function ReplayPage() {
  const { sessionId = "" } = useParams();
  const replay = useReplay(sessionId);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const graph = useRef<Graph | null>(null);
  const [current, setCurrent] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [follow, setFollow] = useState(true);
  const [mode, setModeState] = useState<ChannelMode>("mixed");

  const data = replay.data;
  const hasPlayer = !!data && data.audio.available && data.channel === "voice";
  const lines = useMemo(() => data?.lines ?? [], [data]);
  const active = lineAt(lines, current);

  // The audio element appears once the replay has loaded, so this runs again then.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const time = () => setCurrent(Math.round(audio.currentTime * 1000));
    const meta = () => setDurationMs(Number.isFinite(audio.duration) ? Math.round(audio.duration * 1000) : 0);
    const play = () => setPlaying(true);
    const pause = () => setPlaying(false);
    audio.addEventListener("timeupdate", time);
    audio.addEventListener("loadedmetadata", meta);
    audio.addEventListener("play", play);
    audio.addEventListener("pause", pause);
    audio.addEventListener("ended", pause);
    return () => {
      audio.removeEventListener("timeupdate", time);
      audio.removeEventListener("loadedmetadata", meta);
      audio.removeEventListener("play", play);
      audio.removeEventListener("pause", pause);
      audio.removeEventListener("ended", pause);
    };
  }, [hasPlayer]);

  useEffect(() => () => void graph.current?.ctx.close(), []);

  const ensureGraph = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || graph.current) return;
    graph.current = buildGraph(audio);
    if (graph.current) applyMode(graph.current, mode);
  }, [mode]);

  const setMode = (m: ChannelMode) => {
    setModeState(m);
    ensureGraph();
    if (graph.current) applyMode(graph.current, m);
  };

  const play = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    ensureGraph();
    void graph.current?.ctx.resume();
    void audio.play()?.catch(() => setPlaying(false));
  }, [ensureGraph]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) play();
    else audio.pause();
  }, [play]);

  const seek: Seek = useCallback(
    (ms, andPlay = false) => {
      const top = durationMs > 0 ? durationMs : Number.MAX_SAFE_INTEGER;
      const to = Math.max(0, Math.min(ms, top));
      setCurrent(to);
      setFollow(true);
      const audio = audioRef.current;
      if (audio) {
        audio.currentTime = to / 1000;
        if (andPlay) play();
      }
    },
    [durationMs, play],
  );

  // SM-8 keys.
  useEffect(() => {
    if (!data) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
      const key = e.key.toLowerCase();
      const onButton = e.target instanceof HTMLButtonElement || e.target instanceof HTMLAnchorElement;
      if (key === " " && hasPlayer && !onButton) {
        e.preventDefault();
        toggle();
      } else if (key === "arrowleft" && hasPlayer) {
        seek(current - SKIP_MS);
      } else if (key === "arrowright" && hasPlayer) {
        seek(current + SKIP_MS);
      } else if (key === "j" && active > 0) {
        seek(lines[active - 1].start_ms);
      } else if (key === "k" && active < lines.length - 1) {
        seek(lines[active + 1].start_ms);
      } else if (key === "n") {
        const next = lines.find((l) => l.latency_ms !== null && l.latency_ms > data.latency.slow_ms && l.start_ms > current);
        if (next) seek(next.start_ms);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [data, hasPlayer, toggle, seek, current, active, lines]);

  if (replay.isPending) return <Loading label="Loading the replay" />;
  if (replay.isError) return <ErrorNotice error={replay.error} title="The replay could not be loaded." />;
  const r = replay.data;
  const markers: Marker[] = [
    ...r.lines
      .filter((l) => l.latency_ms !== null && l.latency_ms > r.latency.slow_ms)
      .map((l) => ({ ms: l.start_ms, kind: "slow" as const, label: "Slow turn" })),
    ...(r.judge?.problems ?? [])
      .filter((p) => p.at_ms !== null)
      .map((p) => ({ ms: p.at_ms ?? 0, kind: "problem" as const, label: `Judge: ${p.problem}` })),
  ];

  return (
    <>
      <PageHead title="Replay">
        <p className="actions">
          <Link to="/simulations">Back to simulations</Link>
          <Link to={`/interviews/${r.session_id}`}>Open the interview</Link>
        </p>
      </PageHead>
      <Summary replay={r} />
      {r.timing !== "audio" && (
        <p className="notice" role="status">
          Times are approximate: this run was recorded before transcript times followed the audio.
        </p>
      )}
      {hasPlayer ? (
        <Player
          audioRef={audioRef}
          sessionId={r.session_id}
          current={current}
          durationMs={durationMs}
          playing={playing}
          markers={markers}
          seek={seek}
          toggle={toggle}
          mode={mode}
          setMode={setMode}
        />
      ) : (
        <p className="muted">{r.channel === "text" ? "A text interview: no recording." : "No recording for this run."}</p>
      )}
      <div className="replay-grid">
        <Transcript replay={r} active={active} seek={seek} follow={follow} setFollow={setFollow} />
        <div>
          <JudgePanel judge={r.judge} seek={seek} />
          <ScorecardPanel card={r.scorecard} />
        </div>
      </div>
    </>
  );
}
