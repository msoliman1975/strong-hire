/**
 * ON-1 (mockup #start): after the profile, the only setup input is the resume: a file, pasted
 * text, or pasted LinkedIn experience (the same text path). "Read my resume" uploads it and opens
 * the reading screen.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";

import { resumesApi } from "../../api/inputs";
import { useAuth } from "../../api/hooks";
import { ErrorNotice } from "../../components/ui";
import "../../components/ux/ux.css";
import { readingPath } from "./paths";

const MAX_BYTES = 1024 * 1024;
const ACCEPT = ".pdf,.docx,.txt,.md";

export function StartPage() {
  const auth = useAuth();
  const first = auth.data?.user?.full_name?.trim().split(/\s+/)[0];
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const textId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [linkedin, setLinkedin] = useState(false);
  const [over, setOver] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: resumesApi.upload,
    onSuccess: (accepted) => {
      void queryClient.invalidateQueries({ queryKey: ["resumes"] });
      navigate(readingPath(accepted.resume.id, accepted.job?.id));
    },
  });

  const pick = (f: File | null | undefined) => {
    setProblem(null);
    if (!f) return;
    if (!/\.(pdf|docx|txt|md)$/i.test(f.name)) {
      setProblem("Use a PDF or DOCX file.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setProblem("Resume files can be up to 1 MB.");
      return;
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    pick(e.dataTransfer.files[0]);
  };

  const submit = () => {
    setProblem(null);
    const form = new FormData();
    if (file) form.append("file", file);
    else if (text.trim()) form.append("text", text.trim());
    else {
      setProblem(linkedin ? "Paste your LinkedIn experience first." : "Choose a file or paste your resume first.");
      return;
    }
    upload.mutate(form);
  };

  return (
    <div className="sx-solo">
      <div className="sx-stack" style={{ gap: 8 }}>
        <div className="sx-eyebrow">{first ? `Welcome, ${first}` : "Welcome"}</div>
        <h1 style={{ fontSize: 34 }}>Start with your resume</h1>
        <p className="sx-muted" style={{ fontSize: 17, maxWidth: "60ch" }}>
          Everything in Strong Hire builds on it. Strova reads your resume, finds issues to fix, and suggests the
          stories you can tell in interviews.
        </p>
      </div>
      <div className="sx-card">
        <div
          className="sx-drop"
          data-over={over}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          onClick={() => fileInput.current?.click()}
        >
          <strong>{file ? file.name : "Drop your resume here, or choose a file"}</strong>
          <span className="sx-muted sx-small">
            PDF or DOCX, up to 1 MB. Stored encrypted. You can delete it at any time.
          </span>
          <button
            type="button"
            className="sx-btn ghost sm"
            onClick={(e) => {
              e.stopPropagation();
              fileInput.current?.click();
            }}
          >
            {file ? "Choose another file" : "Choose a file"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            hidden
            aria-label="Resume file"
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </div>
        <div className="sx-field">
          <label htmlFor={textId}>{linkedin ? "Or paste your LinkedIn experience" : "Or paste your resume text"}</label>
          <textarea
            id={textId}
            rows={3}
            placeholder={linkedin ? "Paste the Experience section of your LinkedIn profile" : "Paste the text of your resume"}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (e.target.value) setFile(null);
            }}
          />
        </div>
        {problem && (
          <p className="sx-notice bad" role="alert">
            {problem}
          </p>
        )}
        {upload.isError && <ErrorNotice error={upload.error} />}
        <div className="sx-between">
          <span className="sx-muted sx-small">
            {linkedin ? (
              <>
                Have a resume after all?{" "}
                <button type="button" className="sx-link" onClick={() => setLinkedin(false)}>
                  Paste your resume instead
                </button>
              </>
            ) : (
              <>
                No resume file?{" "}
                <button type="button" className="sx-link" onClick={() => setLinkedin(true)}>
                  Paste your LinkedIn experience
                </button>{" "}
                instead.
              </>
            )}
          </span>
          <button type="button" className="sx-btn" onClick={submit} disabled={upload.isPending}>
            {upload.isPending ? "Sending…" : "Read my resume"}
          </button>
        </div>
      </div>
      <div className="sx-grid3">
        <div className="sx-card tight">
          <h3>Resume breakdown</h3>
          <p className="sx-muted sx-small">Your roles, achievements and skills, the way an interviewer reads them.</p>
        </div>
        <div className="sx-card tight">
          <h3>Resume issues</h3>
          <p className="sx-muted sx-small">Gaps in dates, thin roles and missing skills, to fix or accept.</p>
        </div>
        <div className="sx-card tight">
          <h3>Story ideas</h3>
          <p className="sx-muted sx-small">The achievements that could become your interview stories.</p>
        </div>
      </div>
    </div>
  );
}
