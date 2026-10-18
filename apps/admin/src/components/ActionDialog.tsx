import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { ErrorNotice } from "./ui";

export interface ActionDialogProps {
  /** The dialog is shown while true. */
  open: boolean;
  title: string;
  /** What will happen, repeating the target and the amount (AA-7). */
  summary: ReactNode;
  confirmLabel: string;
  /** Red confirm button, for destructive actions. */
  danger?: boolean;
  /** When set, the admin must type this word to confirm (for example PAUSE). */
  confirmWord?: string;
  /** Extra form fields (amount, end date); shown above the reason. */
  children?: ReactNode;
  /** False while the extra fields are not valid yet. */
  canConfirm?: boolean;
  pending?: boolean;
  error?: unknown;
  /** Called with the reason (AA-6). Close the dialog in the mutation's onSuccess. */
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export const MIN_REASON = 3;

/**
 * A reason + confirm dialog for admin write actions (AA-6, AA-7). Every action asks for a
 * free-text reason, which the API stores in the audit log. Generic: the caller gives the
 * summary, any extra fields and what to do on confirm.
 *
 * Accessible modal: role="dialog" with aria-modal, labelled by its title, focus moves to the
 * first field when it opens and back where it was when it closes, and Escape cancels.
 */
export function ActionDialog(props: ActionDialogProps) {
  // Mounted fresh on each open, so the reason starts empty every time.
  return props.open ? <DialogPanel {...props} /> : null;
}

function DialogPanel({
  title,
  summary,
  confirmLabel,
  danger = false,
  confirmWord,
  children,
  canConfirm = true,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: ActionDialogProps) {
  const id = useId();
  const [reason, setReason] = useState("");
  const [word, setWord] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    const first = panel.current?.querySelector<HTMLElement>("input, select, textarea");
    first?.focus();
    return () => {
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, []);

  const reasonOk = reason.trim().length >= MIN_REASON;
  const wordOk = !confirmWord || word.trim() === confirmWord;
  const ready = reasonOk && wordOk && canConfirm && !pending;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready) onConfirm(reason.trim());
  };

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !pending && onCancel()}>
      <div
        ref={panel}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-summary`}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !pending) onCancel();
        }}
      >
        <form onSubmit={submit}>
          <h2 id={`${id}-title`}>{title}</h2>
          <div id={`${id}-summary`} className="dialog__summary">
            {summary}
          </div>
          {children}
          <div className="field">
            <label htmlFor={`${id}-reason`}>Reason (saved in the audit log)</label>
            <textarea
              id={`${id}-reason`}
              value={reason}
              maxLength={500}
              rows={3}
              onChange={(e) => setReason(e.target.value)}
              aria-invalid={reason.length > 0 && !reasonOk}
            />
          </div>
          {confirmWord && (
            <div className="field">
              <label htmlFor={`${id}-word`}>Type {confirmWord} to confirm</label>
              <input id={`${id}-word`} value={word} autoComplete="off" onChange={(e) => setWord(e.target.value)} />
            </div>
          )}
          {error !== undefined && error !== null && <ErrorNotice error={error} />}
          <div className="row dialog__actions">
            <button type="button" className="btn" onClick={onCancel} disabled={pending}>
              Cancel
            </button>
            <button type="submit" className={danger ? "btn btn--danger" : "btn btn--primary"} disabled={!ready}>
              {pending ? "Working" : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
