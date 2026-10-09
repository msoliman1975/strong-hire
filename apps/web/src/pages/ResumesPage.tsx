import { useNavigate } from "react-router";

import { CvLibrary, useLibraryRefresh } from "../components/LibrarySection";
import { PageHead } from "../components/ui";
import { resumeCheckPath } from "../paths";
import { UploadForm } from "./onboarding/ResumePage";

/** LB-1: the saved CVs, with add, rename and delete. */
export function ResumesPage() {
  const navigate = useNavigate();
  const refresh = useLibraryRefresh();

  return (
    <div className="page--narrow">
      <PageHead title="Resumes">
        <p>Your saved CVs. Pick one when you set up an interview rehearsal. Deleting a CV keeps your reports.</p>
      </PageHead>
      <CvLibrary />
      <UploadForm
        onUploaded={(accepted) => {
          refresh();
          navigate(resumeCheckPath(accepted.resume.id));
        }}
        onUseSaved={(saved) => navigate(resumeCheckPath(saved.id))}
      />
    </div>
  );
}
