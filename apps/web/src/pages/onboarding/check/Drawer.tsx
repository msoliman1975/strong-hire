/**
 * RSD-14: a drawer is a modal dialog from the right, at most 460 px and full width on phones. It
 * traps focus, closes on Esc, on the backdrop and on its close button, and returns focus to the
 * element that opened it.
 */
import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Drawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const headingId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open) {
      opener.current = document.activeElement as HTMLElement | null;
      if (typeof dialog.showModal === "function") {
        if (!dialog.open) dialog.showModal();
      } else dialog.setAttribute("open", "");
      dialog.querySelector<HTMLElement>(".cvc-drawer__close")?.focus();
    } else if (dialog.open || dialog.hasAttribute("open")) {
      if (typeof dialog.close === "function") dialog.close();
      dialog.removeAttribute("open");
      opener.current?.focus();
    }
  }, [open]);

  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <dialog
      ref={ref}
      className="cvc-drawer"
      aria-labelledby={headingId}
      aria-modal="true"
      onKeyDown={onKeyDown}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        // A click on the backdrop lands on the dialog itself, outside its panel.
        if (e.target === ref.current) onClose();
      }}
    >
      {open && (
        <div className="cvc-drawer__panel">
          <div className="cvc-drawer__head">
            <h2 id={headingId}>{title}</h2>
            <button type="button" className="sx-btn quiet sm cvc-drawer__close" aria-label="Close" onClick={onClose}>
              ✕
            </button>
          </div>
          <div className="cvc-drawer__body">{children}</div>
        </div>
      )}
    </dialog>
  );
}
