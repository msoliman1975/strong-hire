/**
 * SC-17 (UI, RMAP-7): the reply box of a crafting session. It grows with the text up to about
 * half the screen, then scrolls; Expand opens a full-width writing view, and Esc returns. "Skip
 * this" and "Move on" are quick replies (SC-5). Enter sends and Shift+Enter adds a line.
 * SC-18: a toolbar and Ctrl+B / Ctrl+I format the reply in light Markdown.
 */
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { markdownKeys, MarkdownToolbar } from "../../components/markdown/markdown";

export const REPLY_MAX_CHARS = 4000;
export const QUICK_REPLIES = [
  { label: "Skip this", text: "skip" },
  { label: "Move on", text: "move on" },
] as const;

/** Height for a textarea that grows with its text, capped at `max` pixels. */
function useGrow(ref: React.RefObject<HTMLTextAreaElement | null>, value: string, max: () => number) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const height = Math.min(el.scrollHeight, max());
    el.style.height = `${height}px`;
    el.style.overflowY = el.scrollHeight > height ? "auto" : "hidden";
  }, [ref, value, max]);
}

const halfScreen = () => Math.max(160, Math.round((typeof window === "undefined" ? 800 : window.innerHeight) / 2));

export function ReplyBox({
  value,
  onChange,
  onSend,
  onQuick,
  busy,
  quick,
  children,
}: {
  value: string;
  onChange: (next: string) => void;
  onSend: () => void;
  onQuick: (text: string) => void;
  busy: boolean;
  quick: boolean;
  children?: ReactNode; // the mic and Talk instead (CO-6)
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const big = useRef<HTMLTextAreaElement>(null);
  const expandButton = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState(false);
  useGrow(box, value, halfScreen);
  const boxKeys = markdownKeys(onChange);
  const bigKeys = markdownKeys(onChange);

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (boxKeys.onKeyDown(e)) return;
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (value.trim() && !busy) onSend();
    }
  };

  const close = () => {
    setExpanded(false);
    window.setTimeout(() => expandButton.current?.focus(), 0);
  };

  useEffect(() => {
    if (expanded) big.current?.focus();
  }, [expanded]);

  return (
    <form
      className="craft-reply"
      aria-label="Reply to your coach"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() && !busy) onSend();
      }}
    >
      {quick && (
        <div className="craft-reply__quick" role="group" aria-label="Quick replies">
          {QUICK_REPLIES.map((q) => (
            <button key={q.text} type="button" className="btn btn--quiet" disabled={busy} onClick={() => onQuick(q.text)}>
              {q.label}
            </button>
          ))}
        </div>
      )}
      <MarkdownToolbar target={box} onChange={onChange} />
      <label htmlFor="coach-reply" className="visually-hidden">
        Your reply
      </label>
      <textarea
        id="coach-reply"
        ref={box}
        className="craft-reply__box"
        rows={3}
        value={value}
        maxLength={REPLY_MAX_CHARS}
        placeholder="Type your answer. Shift+Enter adds a line."
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        onPaste={boxKeys.onPaste}
      />
      <div className="craft-reply__bar">
        {children}
        <button
          ref={expandButton}
          type="button"
          className="btn btn--quiet"
          aria-haspopup="dialog"
          onClick={() => setExpanded(true)}
        >
          Expand
        </button>
        <button className="btn" type="submit" disabled={!value.trim() || busy}>
          Send
        </button>
      </div>
      {expanded && (
        <div
          className="craft-expand"
          role="dialog"
          aria-modal="true"
          aria-labelledby="craft-expand-title"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              close();
            }
          }}
        >
          <div className="craft-expand__inner">
            <h2 id="craft-expand-title" className="craft-expand__title">
              Write your reply
            </h2>
            <MarkdownToolbar target={big} onChange={onChange} />
            <label htmlFor="coach-reply-expanded" className="visually-hidden">
              Your reply
            </label>
            <textarea
              id="coach-reply-expanded"
              ref={big}
              className="craft-expand__box"
              value={value}
              maxLength={REPLY_MAX_CHARS}
              onChange={(e) => onChange(e.target.value)}
              onPaste={bigKeys.onPaste}
              onKeyDown={(e) => {
                if (bigKeys.onKeyDown(e)) return;
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && value.trim() && !busy) {
                  e.preventDefault();
                  close();
                  onSend();
                }
              }}
            />
            <div className="craft-expand__bar">
              <span className="muted small">Esc returns to the conversation. Ctrl+Enter sends.</span>
              <button type="button" className="btn btn--secondary" onClick={close}>
                Back to the conversation
              </button>
              <button
                type="button"
                className="btn"
                disabled={!value.trim() || busy}
                onClick={() => {
                  close();
                  onSend();
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </form>
  );
}
