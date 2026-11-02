/**
 * RC-1 to RC-8: which of your resumes fits this role best. Runs only when the user asks (RC-1).
 * Each resume gets a gap analysis; the API ranks them in code and explains the pick (RC-3). The
 * chosen or recommended resume's gaps follow, most severe first: one another resume covers can
 * be copied in with Add to resume or dismissed (RC-4); one no resume covers offers Craft a story
 * (RC-5). Use this one is always the user's click (RC-6). The comparison is saved on the role and
 * says when it is out of date (RC-8).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { compareApi, compareKeys, useResumeComparison } from "../../api/compare";
import type { ComparedResume, ComparisonGap, ResumeComparisonOut } from "../../api/types";
import { Strova } from "../../components/strova";
import { ErrorNotice, Loading } from "../../components/ui";
import { newCoachPath } from "../coach/paths";

const SEVERITY = { high: { label: "High", cls: "bad" }, medium: { label: "Medium", cls: "warn" }, low: { label: "Low", cls: "" } } as const;

/** RC-5: a coach session for the role that starts from the gap. */
export function craftPath(jobId: string, gap: ComparisonGap) {
  const need = gap.related_requirement ?? gap.summary;
  return newCoachPath({ job: jobId, ask: `Help me craft a story that shows this: ${need}.` });
}

function when(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function name(r: ComparedResume | undefined) {
  return r?.resume_name ?? "A deleted resume";
}

/** One-line summary of a saved comparison (RC-8), for the role page. */
export function comparisonSummary(c: ResumeComparisonOut) {
  const best = c.resumes.find((r) => r.resume_id === c.recommended_resume_id);
  const count = `Compared ${c.resumes.length} resumes on ${when(c.created_at)}`;
  if (c.status === "running") return `${count} · Strova is still reading them`;
  if (!best) return `${count} · no analysis finished`;
  return `${count} · ${name(best)} fit best`;
}

function ResumeRow({
  r,
  c,
  pickedId,
  onUse,
  busy,
}: {
  r: ComparedResume;
  c: ResumeComparisonOut;
  pickedId: string | null;
  onUse: (resumeId: string) => void;
  busy: boolean;
}) {
  const recommended = r.resume_id === c.recommended_resume_id;
  const inUse = r.resume_id === pickedId;
  const ready = r.status === "ready" && !r.deleted;
  return (
    <div className="sx-list-row" data-testid="compared-resume">
      <div className="sx-stack" style={{ gap: 3 }}>
        <div className="sx-row">
          {recommended && (
            <span className="sx-chip ok" title="Strova's pick">
              Best fit
            </span>
          )}
          <strong>{name(r)}</strong>
          {r.is_main && <span className="sx-chip">Main</span>}
          {inUse && <span className="sx-chip t">In use</span>}
        </div>
        <span className="sx-small sx-muted">
          {r.must_haves_total > 0 && `${r.must_haves_shown} of ${r.must_haves_total} must-haves shown`}
          {r.status === "running" && " · Strova is reading it"}
          {r.status === "failed" && ` · ${r.error ?? "The analysis failed."}`}
          {r.stale && " · changed since"}
        </span>
      </div>
      <div className="sx-row">
        {r.match_score !== null && <span className="sx-mono">Match {r.match_score}</span>}
        {ready && !inUse && c.status === "ready" && (
          <button type="button" className={`sx-btn sm${recommended ? "" : " ghost"}`} disabled={busy} onClick={() => onUse(r.resume_id)}>
            Use this one
          </button>
        )}
      </div>
    </div>
  );
}

function GapRow({
  gap,
  jobId,
  focusName,
  onAdd,
  onDismiss,
  busy,
}: {
  gap: ComparisonGap;
  jobId: string;
  focusName: string;
  onAdd: () => void;
  onDismiss: () => void;
  busy: boolean;
}) {
  const s = SEVERITY[gap.severity];
  const source = gap.source;
  return (
    <div className="sx-list-row" data-testid="comparison-gap">
      <div className="sx-stack" style={{ gap: 4, flex: 1, minWidth: 220 }}>
        <div className="sx-row">
          <span className={`sx-chip ${s.cls}`}>{s.label}</span>
          <strong>{gap.summary}</strong>
        </div>
        {source ? (
          <span className="sx-small">
            Your <strong>{source.resume_name}</strong> resume shows this: “{source.line}”
            {gap.status === "added" && <span className="sx-muted"> · Added to {focusName}</span>}
            {gap.status === "open" && !source.can_add && (
              <span className="sx-muted">
                {" "}
                · {source.company ? `${focusName} doesn't list ${source.company}, so add it by hand.` : "Add it by hand."}
              </span>
            )}
          </span>
        ) : (
          <span className="sx-small sx-muted">None of your resumes shows this.</span>
        )}
      </div>
      <div className="sx-row">
        {source && gap.status === "open" && source.can_add && (
          <button type="button" className="sx-btn sm" disabled={busy} onClick={onAdd}>
            Add to resume
          </button>
        )}
        {source && gap.status === "open" && (
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={onDismiss}>
            Dismiss
          </button>
        )}
        {!source && (
          <Link className="sx-btn ghost sm" to={craftPath(jobId, gap)}>
            Craft a story
          </Link>
        )}
      </div>
    </div>
  );
}

/**
 * The comparison for one role. `pickedId` is the resume the role uses now (on Add a target role:
 * the one it will be created with). `onUse` handles Use this one; without it the API call moves
 * the role to the resume (RC-6, role page).
 */
export function ResumeComparison({
  jobId,
  pickedId,
  onUse,
  beforeStart,
}: {
  jobId: string;
  pickedId: string | null;
  onUse?: (resumeId: string) => void;
  /** Runs before a comparison starts, for example to save the posting edits on Add a role. */
  beforeStart?: () => Promise<void>;
}) {
  const client = useQueryClient();
  const query = useResumeComparison(jobId);
  const set = (c: ResumeComparisonOut) => client.setQueryData(compareKeys.comparison(jobId), c);
  const start = useMutation({
    mutationFn: async () => {
      if (beforeStart) await beforeStart();
      return compareApi.start(jobId);
    },
    onSuccess: set,
  });
  const use = useMutation({
    mutationFn: async (resumeId: string) => {
      const c = query.data;
      if (!c) throw new Error("Compare your resumes first.");
      if (onUse) {
        onUse(resumeId);
        return c;
      }
      return compareApi.use(c.id, resumeId);
    },
    onSuccess: (c) => {
      set(c);
      // The role's interviews, plan, match score and gap report follow the resume.
      if (!onUse) void client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "resume-comparison" });
    },
  });
  const hint = useMutation({
    mutationFn: ({ key, add }: { key: string; add: boolean }) => {
      const c = query.data;
      if (!c) throw new Error("Compare your resumes first.");
      return add ? compareApi.addLine(c.id, key) : compareApi.dismiss(c.id, key);
    },
    onSuccess: (c, { add }) => {
      set(c);
      if (add) void client.invalidateQueries({ queryKey: ["resumes"] });
    },
  });

  if (query.isPending) return <Loading label="Loading the comparison" />;
  if (query.isError) return <ErrorNotice error={query.error} />;
  const c = query.data;
  const busy = start.isPending || use.isPending || hint.isPending;
  const startButton = (label: string) => (
    <button type="button" className="sx-btn sm" disabled={busy} onClick={() => start.mutate()}>
      {start.isPending ? "Starting…" : label}
    </button>
  );

  if (!c) {
    return (
      <div className="sx-stack" data-testid="resume-comparison">
        <p className="sx-small sx-muted">
          Strova reads each of your resumes against this job and recommends the one that fits best, with its gaps. Unchanged
          resumes are not read again.
        </p>
        {start.isError && <ErrorNotice error={start.error} />}
        <div>{startButton("Compare my resumes")}</div>
      </div>
    );
  }

  // On the role page the server knows the role's resume; on Add a target role it is the local pick.
  const inUseId = onUse ? pickedId : (c.role_resume_id ?? pickedId);
  const focus = c.resumes.find((r) => r.resume_id === c.focus_resume_id);
  const focusName = name(focus);
  const shown = c.gaps.filter((g) => g.status !== "dismissed");
  return (
    <div className="sx-stack" data-testid="resume-comparison">
      {c.out_of_date && (
        <div className="sx-notice warn sx-small sx-between" data-testid="comparison-out-of-date">
          <span>{c.out_of_date_reason}</span>
          {startButton("Compare again")}
        </div>
      )}
      {c.status === "running" && (
        <div className="sx-row">
          <Strova mode="analysing" size={28} />
          <span className="sx-small">Strova is reading your resumes against this job. The must-have counts are ready now.</span>
        </div>
      )}
      {c.reason && (
        <p className="sx-small" data-testid="comparison-reason">
          {c.reason}
        </p>
      )}
      <div>
        {c.resumes.map((r) => (
          <ResumeRow key={r.resume_id} r={r} c={c} pickedId={inUseId} onUse={(id) => use.mutate(id)} busy={busy} />
        ))}
      </div>
      {start.isError && <ErrorNotice error={start.error} />}
      {use.isError && <ErrorNotice error={use.error} />}
      {c.status === "ready" && focus && (
        <section className="sx-stack" aria-labelledby="comparison-gaps-heading" style={{ gap: 4 }}>
          <h3 id="comparison-gaps-heading">Gaps in {focusName}</h3>
          {shown.length === 0 && <p className="sx-small sx-muted">Strova found no gaps to show for this resume.</p>}
          {shown.map((g) => (
            <GapRow
              key={g.key}
              gap={g}
              jobId={jobId}
              focusName={focusName}
              busy={busy}
              onAdd={() => hint.mutate({ key: g.key, add: true })}
              onDismiss={() => hint.mutate({ key: g.key, add: false })}
            />
          ))}
          {hint.isError && <ErrorNotice error={hint.error} />}
        </section>
      )}
      {c.status === "failed" && <p className="sx-notice warn sx-small">Strova could not read your resumes this time. Compare again.</p>}
      {!c.out_of_date && c.status !== "running" && (
        <div>
          <button type="button" className="sx-btn quiet sm" disabled={busy} onClick={() => start.mutate()}>
            Compare again
          </button>
        </div>
      )}
    </div>
  );
}
