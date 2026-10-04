/** Form validation is the only input logic in the web app. */
import { describe, expect, it } from "vitest";

import { validateJobInput } from "./pages/onboarding/NewJobPage";
import { MAX_RESUME_BYTES, validateResumeInput } from "./pages/onboarding/ResumePage";

describe("job posting input", () => {
  it("needs a link or text", () => {
    expect(validateJobInput("", "")).toMatch(/Paste the job posting/);
  });
  it("accepts an http(s) link", () => {
    expect(validateJobInput("https://boards.example.com/jobs/1", "")).toBeNull();
  });
  it("rejects other links", () => {
    expect(validateJobInput("ftp://example.com/job", "")).toMatch(/http/);
    expect(validateJobInput("not a url", "")).toMatch(/http/);
  });
  it("needs enough pasted text", () => {
    expect(validateJobInput("", "short")).toMatch(/too short/);
    expect(validateJobInput("", "x".repeat(100))).toBeNull();
  });
});

describe("resume input", () => {
  const file = (name: string, size = 10) => new File([new Uint8Array(size)], name);
  it("needs a file or text", () => {
    expect(validateResumeInput(null, " ")).toMatch(/Choose a PDF or DOCX/);
    expect(validateResumeInput(null, "My resume")).toBeNull();
  });
  it("accepts PDF and DOCX only", () => {
    expect(validateResumeInput(file("cv.pdf"), "")).toBeNull();
    expect(validateResumeInput(file("CV.DOCX"), "")).toBeNull();
    expect(validateResumeInput(file("cv.png"), "")).toMatch(/PDF or DOCX/);
  });
  it("rejects files over 10 MB", () => {
    expect(validateResumeInput(file("cv.pdf", MAX_RESUME_BYTES + 1), "")).toMatch(/10 MB/);
  });
});
