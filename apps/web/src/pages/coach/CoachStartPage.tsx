/**
 * CO-2: `/coach/new?story=&skill=&job=` starts a coach session and replaces itself with the
 * session page. Links on Home, the plan's story fit and the workbench open it, so they stay links.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { ErrorNotice, Loading } from "../../components/ui";
import { storiesPath } from "../stories/paths";
import { coachApi, type StartCoachRequest } from "./api";
import { coachPath } from "./paths";

export function CoachStartPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const started = useRef(false);
  const start = useMutation({
    mutationFn: (body: StartCoachRequest) => coachApi.start(body),
    onSuccess: (detail) => navigate(coachPath(detail.session.id), { replace: true }),
  });

  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice; start one session
    started.current = true;
    start.mutate({
      style: "gentle", // switched on the session page (CO-5)
      channel: "text",
      story_id: params.get("story") || null,
      target_skill: (params.get("skill") || null) as StartCoachRequest["target_skill"],
      job_target_id: params.get("job") || null,
    });
  }, [params, start]);

  return (
    <div className="coach stack">
      {start.isError ? (
        <>
          <ErrorNotice error={start.error} title="The coach session did not start" />
          <p>
            <Link className="text-link" to={storiesPath}>
              Back to your stories
            </Link>
          </p>
        </>
      ) : (
        <Loading label="Starting your coach session" />
      )}
    </div>
  );
}
