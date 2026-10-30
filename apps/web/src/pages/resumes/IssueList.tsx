/**
 * Resume issues as the mockups show them (#resume-check, #cv): the title, the facts and one line
 * of advice, with the fix and accept actions. Fix opens the full editor (IN-12); accept is stored
 * at once (PUT .../accepted-issues).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { resumesApi } from "../../api/inputs";
import type { ResumeIssues } from "../../api/types";
import { ErrorNotice } from "../../components/ui";
import { resumeCheckPath } from "../../paths";

type Issue = ResumeIssues["open"][number];

/** The detail and the first sentence of the advice: "10 words. Say who you are, …". */
export function issueLine(issue: Issue): string {
  const advice = /^(.+?[.!?])(\s|$)/.exec(issue.why.trim())?.[1] ?? issue.why;
  const detail = issue.detail.trim().replace(/"/g, "");
  return `${detail}${/[.!?]$/.test(detail) ? "" : "."} ${advice}`;
}

export function IssueList({ resumeId, issues, compactActions = false }: { resumeId: string; issues: Issue[]; compactActions?: boolean }) {
  const queryClient = useQueryClient();
  const accept = useMutation({
    mutationFn: (key: string) => resumesApi.setAcceptedIssue(resumeId, key, true),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["resumes"] }),
  });
  return (
    <>
      {accept.isError && <ErrorNotice error={accept.error} />}
      {issues.map((issue, i) => {
        const strong = issue.severity !== "low";
        return (
          <div key={issue.key} className={`sx-notice ${strong ? "warn" : "ground"}`}>
            <strong style={strong ? { color: "var(--sh-warn-ink)" } : undefined}>{issue.title}</strong>
            <br />
            <span className={`sx-small${strong ? "" : " sx-muted"}`}>{issueLine(issue)}</span>
            <div className="sx-row sx-small" style={{ marginTop: 6 }}>
              <Link
                className={compactActions ? "sx-btn quiet sm" : `sx-btn sm${i === 0 && strong ? "" : " ghost"}`}
                style={compactActions ? { padding: 0 } : undefined}
                to={resumeCheckPath(resumeId)}
              >
                {issue.fixLabel}
              </Link>
              <button type="button" className="sx-btn quiet sm" onClick={() => accept.mutate(issue.key)} disabled={accept.isPending}>
                {issue.acceptLabel}
              </button>
            </div>
          </div>
        );
      })}
    </>
  );
}
