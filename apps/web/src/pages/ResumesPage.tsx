import { useNavigate } from "react-router";

import { useResumes } from "../api/hooks";
import { CvLibrary, useLibraryRefresh } from "../components/LibrarySection";
import { PageHead } from "../components/ui";
import { MAX_RESUME_MB, MAX_RESUMES } from "../limits";
import { resumeCheckPath } from "../paths";
import { useFeature } from "../theme/features";
import { UploadForm } from "./onboarding/ResumePage";

/** LB-1: the saved CVs, with add, rename and delete. */
export function ResumesPage() {
  const navigate = useNavigate();
  const refresh = useLibraryRefresh();
  const v2 = useFeature("v2_enabled");
  const resumes = useResumes();
  const onFile = (resumes.data ?? []).filter((r) => !r.deleted).length;

  return (
    <div className="page--narrow">
      <PageHead title="Resumes">
        <p>Your saved CVs. Pick one when you set up an interview rehearsal. Deleting a CV keeps your reports.</p>
        {/* R3: the limits, as the API enforces them. */}
        {v2 && resumes.data && (
          <p className="muted small" data-testid="resume-limit">
            {onFile} of {MAX_RESUMES} · up to {MAX_RESUME_MB} MB each
            {onFile >= MAX_RESUMES && " · Delete one to add another."}
          </p>
        )}
      </PageHead>
      <CvLibrary />
      <UploadForm
        onUploaded={(accepted) => {
          refresh();
          navigate(resumeCheckPath(accepted.resume.id, accepted.job?.id));
        }}
        onUseSaved={(saved) => navigate(resumeCheckPath(saved.id))}
      />
    </div>
  );
}
