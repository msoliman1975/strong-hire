/**
 * SC-18 (D-14, RMAP-7): the light Markdown users write in the reply box and the slot editors:
 * **bold**, *italic*, bullet lists and numbered lists. Line breaks are kept.
 *
 * - `Markdown` renders that subset as React elements. There is no HTML string anywhere, so raw
 *   HTML in the text is shown as text, never run.
 * - `MarkdownToolbar` and `markdownKeys` format a textarea: B, I, bullets and numbers, Ctrl+B and
 *   Ctrl+I, and rich text pasted from elsewhere becomes Markdown.
 */
import "./markdown.css";

import { Fragment, type ClipboardEvent, type KeyboardEvent, type ReactNode, type RefObject } from "react";

// --- rendering ---------------------------------------------------------------------------------

const INLINE = /(\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)/g;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (/^(\*\*|__).+\1$/.test(part)) return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>;
    if (/^([*_]).+\1$/.test(part) && part.length > 2) return <em key={`${key}-${i}`}>{part.slice(1, -1)}</em>;
    return <Fragment key={`${key}-${i}`}>{part}</Fragment>;
  });
}

const BULLET = /^\s*[-*+]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;

/** The light Markdown subset as React elements. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const list = BULLET.test(line) ? "ul" : NUMBER.test(line) ? "ol" : null;
    if (list) {
      const items: string[] = [];
      const mark = list === "ul" ? BULLET : NUMBER;
      while (i < lines.length && mark.test(lines[i])) items.push(lines[i++].replace(mark, ""));
      const Tag = list;
      blocks.push(
        <Tag key={`b${i}`} className="md-list">
          {items.map((item, j) => (
            <li key={j}>{inline(item, `l${i}-${j}`)}</li>
          ))}
        </Tag>,
      );
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !BULLET.test(lines[i]) && !NUMBER.test(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={`b${i}`}>
        {para.map((l, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {inline(l, `p${i}-${j}`)}
          </Fragment>
        ))}
      </p>,
    );
  }
  return <div className={className ? `md ${className}` : "md"}>{blocks}</div>;
}

// --- editing -----------------------------------------------------------------------------------

export interface Edit {
  value: string;
  start: number;
  end: number;
}

/** Wrap the selection in a mark (`**` or `*`), or unwrap it when it is already wrapped. */
export function wrap(value: string, start: number, end: number, mark: string): Edit {
  const before = value.slice(0, start);
  const chosen = value.slice(start, end);
  const after = value.slice(end);
  if (before.endsWith(mark) && after.startsWith(mark)) {
    return {
      value: before.slice(0, -mark.length) + chosen + after.slice(mark.length),
      start: start - mark.length,
      end: end - mark.length,
    };
  }
  return { value: `${before}${mark}${chosen}${mark}${after}`, start: start + mark.length, end: end + mark.length };
}

/** Make the selected lines a bullet or numbered list, or plain lines again if they already are. */
export function list(value: string, start: number, end: number, kind: "bullet" | "number"): Edit {
  const from = value.lastIndexOf("\n", start - 1) + 1;
  const toBreak = value.indexOf("\n", end);
  const to = toBreak === -1 ? value.length : toBreak;
  const lines = value.slice(from, to).split("\n");
  const mark = kind === "bullet" ? BULLET : NUMBER;
  const already = lines.every((l) => mark.test(l));
  const next = lines
    .map((l, i) => {
      const bare = l.replace(BULLET, "").replace(NUMBER, "");
      if (already) return bare;
      return kind === "bullet" ? `- ${bare}` : `${i + 1}. ${bare}`;
    })
    .join("\n");
  return { value: value.slice(0, from) + next + value.slice(to), start: from, end: from + next.length };
}

/** Rich text pasted from elsewhere (HTML) as the Markdown subset; other tags become plain text. */
export function htmlToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const walk = (node: Node, ordered = false, index = { n: 0 }): string => {
    if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? "").replace(/\s+/g, " ");
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const el = node as Element;
    const tag = el.tagName.toLowerCase();
    const kids = (o = false, idx = { n: 0 }) => Array.from(el.childNodes).map((c) => walk(c, o, idx)).join("");
    const bold = tag === "b" || tag === "strong" || /font-weight:\s*(bold|[6-9]00)/.test(el.getAttribute("style") ?? "");
    const italic = tag === "i" || tag === "em" || /font-style:\s*italic/.test(el.getAttribute("style") ?? "");
    if (tag === "br") return "\n";
    if (tag === "ul") return `\n${kids(false)}\n`;
    if (tag === "ol") return `\n${kids(true, { n: 0 })}\n`;
    if (tag === "li") {
      index.n += 1;
      return `${ordered ? `${index.n}.` : "-"} ${kids().trim()}\n`;
    }
    if (tag === "p" || tag === "div" || /^h[1-6]$/.test(tag)) return `\n${kids().trim()}\n`;
    const text = kids();
    if (!text.trim()) return text;
    if (bold && italic) return `***${text.trim()}***`;
    if (bold) return `**${text.trim()}**`;
    if (italic) return `*${text.trim()}*`;
    return text;
  };
  return walk(doc.body)
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

type Area = RefObject<HTMLTextAreaElement | null>;

function apply(el: HTMLTextAreaElement | null, onChange: (v: string) => void, make: (v: string, s: number, e: number) => Edit) {
  if (!el) return;
  const out = make(el.value, el.selectionStart, el.selectionEnd);
  onChange(out.value);
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(out.start, out.end);
  });
}

/** Ctrl+B and Ctrl+I (Cmd on a Mac), and rich-text paste, for a textarea. */
export function markdownKeys(onChange: (v: string) => void) {
  return {
    onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return false;
      const key = e.key.toLowerCase();
      if (key !== "b" && key !== "i") return false;
      e.preventDefault();
      apply(e.currentTarget, onChange, (v, s, en) => wrap(v, s, en, key === "b" ? "**" : "*"));
      return true;
    },
    onPaste: (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const html = e.clipboardData.getData("text/html");
      if (!html) return;
      const md = htmlToMarkdown(html);
      if (!md) return;
      e.preventDefault();
      apply(e.currentTarget, onChange, (v, s, en) => ({ value: v.slice(0, s) + md + v.slice(en), start: s + md.length, end: s + md.length }));
    },
  };
}

/** SC-18: B, I, bullets and numbers over a textarea. */
export function MarkdownToolbar({ target, onChange, label = "Formatting" }: { target: Area; onChange: (v: string) => void; label?: string }) {
  const button = (name: string, shortcut: string | undefined, glyph: ReactNode, make: (v: string, s: number, e: number) => Edit) => (
    <button
      type="button"
      className="md-toolbar__btn"
      aria-label={name}
      title={shortcut ? `${name} (${shortcut})` : name}
      aria-keyshortcuts={shortcut?.replace("Ctrl", "Control")}
      onMouseDown={(e) => e.preventDefault()} // keep the selection in the textarea
      onClick={() => apply(target.current, onChange, make)}
    >
      {glyph}
    </button>
  );
  return (
    <div className="md-toolbar" role="toolbar" aria-label={label}>
      {button("Bold", "Ctrl+B", <b>B</b>, (v, s, e) => wrap(v, s, e, "**"))}
      {button("Italic", "Ctrl+I", <i>I</i>, (v, s, e) => wrap(v, s, e, "*"))}
      {button("Bulleted list", undefined, <span aria-hidden="true">•</span>, (v, s, e) => list(v, s, e, "bullet"))}
      {button("Numbered list", undefined, <span aria-hidden="true">1.</span>, (v, s, e) => list(v, s, e, "number"))}
    </div>
  );
}
