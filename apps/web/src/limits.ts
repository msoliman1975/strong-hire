/**
 * The v2 input limits (canvas board R3 Interviews), the same numbers the API enforces (session
 * A1): up to 5 resumes on file, 1 MB per resume file, and 2,500 words per job description. The
 * web app checks them first, so the API's 413 and 422 refusals are rare; when one comes, it is
 * shown in plain words.
 */
import { ApiError } from "./api/client";

export const MAX_RESUMES = 5;
export const MAX_RESUME_MB = 1;
export const MAX_RESUME_BYTES_V2 = MAX_RESUME_MB * 1024 * 1024;
export const JD_MAX_WORDS = 2500;
/** The word counter turns amber here. Real postings run 300 to 1,200 words. */
export const JD_WARN_WORDS = 2000;

export const fmt = (n: number) => n.toLocaleString("en-US");

export const countWords = (text: string) => {
  const t = text.trim();
  return t === "" ? 0 : t.split(/\s+/).length;
};

export const RESUME_TOO_BIG = `This file is over ${MAX_RESUME_MB} MB. Save a smaller PDF (without embedded images), or paste the text instead.`;
export const RESUMES_FULL = `You have ${MAX_RESUMES} resumes on file, the most you can keep. Delete one on the Resumes page to add another.`;
export const JD_TOO_LONG = `This job description is over ${fmt(JD_MAX_WORDS)} words. Trim the benefits and company boilerplate.`;

/** strong_api.inputs.limits (A1, #173): the codes of its limit refusals. */
const LIMIT_MESSAGES: Record<string, string> = {
  file_too_large: RESUME_TOO_BIG, // 413
  resume_limit: RESUMES_FULL, // 422
  posting_too_long: JD_TOO_LONG, // 422
};

/**
 * A limit refusal from the API, in plain words; any other error as it came. The API's codes come
 * first (A1); a 413 without one is still a file over the size limit, and a 422 or 409 that names
 * the limit in its message is matched by its words.
 */
export function friendlyLimitError(error: unknown): unknown {
  if (!(error instanceof ApiError)) return error;
  const known = error.code ? LIMIT_MESSAGES[error.code] : undefined;
  if (known) return new Error(known);
  const said = `${error.code ?? ""} ${error.message}`.toLowerCase();
  if (error.status === 413) return new Error(RESUME_TOO_BIG);
  if (error.status === 422 || error.status === 409) {
    if (/word/.test(said)) return new Error(JD_TOO_LONG);
    if (/resume|cv/.test(said) && /limit|many|max|full/.test(said)) return new Error(RESUMES_FULL);
    if (/size|large|mb|bytes/.test(said)) return new Error(RESUME_TOO_BIG);
  }
  return error;
}
