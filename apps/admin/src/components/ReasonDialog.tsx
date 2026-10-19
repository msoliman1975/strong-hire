import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { ErrorNotice } from "./ui";

const MIN_REASON = 3;

/**
 * Confirm dialog for an admin write (AA-6, AA-7): repeats what will change, asks for the reason
 * that goes in the audit log, and for some actions makes the admin type a word (`PAUSE`).
 */
export function ReasonDialog({
  title,
  children,
  confirmLabel,
  danger = false,
  requireWord,
  pending = false,
  disabled = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  /** What will change: the target and the new value. */
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  /** AA-7: the admin must type this word to confirm. */
  requireWord?: string;
  pending?: boolean;
  /** The caller's own fields are not complete yet (for example a required choice). */
  disabled?: boolean;
  error?: unknown;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [word, setWord] = useState("");
  const titleId = useId();
  const reasonId = useId();
  const wordId = useId();
  const first = useRef<HTMLTextAreaElement>(null);
  const cancel = useRef(onCancel);

  useEffect(() => {
    cancel.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") cancel.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const reasonOk = reason.trim().length >= MIN_REASON;
  const wordOk = !requireWord || word.trim() === requireWord;

  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId}>{title}</h2>
        <div className="dialog__summary">{children}</div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (reasonOk && wordOk && !pending && !disabled) onConfirm(reason.trim());
          }}
        >
          <div className="field">
            <label htmlFor={reasonId}>Reason (saved in the audit log)</label>
            <textarea
              id={reasonId}
              ref={first}
              rows={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          {requireWord && (
            <div className="field">
              <label htmlFor={wordId}>
                Type <strong>{requireWord}</strong> to confirm
              </label>
              <input
                id={wordId}
                autoComplete="off"
                value={word}
                onChange={(e) => setWord(e.target.value)}
              />
            </div>
          )}
          {error !== undefined && error !== null && <ErrorNotice error={error} />}
          <div className="row dialog__actions">
            <button type="button" className="btn" onClick={onCancel}>
              Cancel
            </button>
            <button
              type="submit"
              className={danger ? "btn btn--danger" : "btn btn--primary"}
              disabled={!reasonOk || !wordOk || pending || disabled}
            >
              {pending ? "Saving" : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
