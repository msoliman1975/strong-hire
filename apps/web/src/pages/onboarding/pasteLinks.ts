/**
 * IN-4: pasting rich text (an email, a doc) into a plain textarea keeps only the visible text, so
 * links lose their address. These helpers turn the pasted HTML into text where each link is
 * written in markdown, `[text](https://...)`, or as the bare URL when the text is the URL.
 */
import type { ClipboardEvent } from "react";

const SAFE_HREF = /^(https?:|mailto:)/i;
const BLOCKS = new Set(["P", "DIV", "LI", "TR", "H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "PRE", "SECTION"]);

/** The pasted HTML as plain text with its links kept. Null when it has no links worth keeping. */
export function htmlToTextWithLinks(html: string): string | null {
  const doc = new DOMParser().parseFromString(html, "text/html");
  if (!doc.body.querySelector("a[href]")) return null;
  let out = "";
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += (node.textContent ?? "").replace(/\s+/g, " ");
      return;
    }
    if (!(node instanceof Element)) return;
    if (node.tagName === "SCRIPT" || node.tagName === "STYLE") return;
    if (node.tagName === "BR") {
      out += "\n";
      return;
    }
    const href = node.tagName === "A" ? (node.getAttribute("href") ?? "").trim() : "";
    if (href && SAFE_HREF.test(href)) {
      const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
      const bare = href.replace(/^mailto:/i, "");
      out += !text || text === href || text === bare ? bare : `[${text}](${href})`;
      return;
    }
    const block = BLOCKS.has(node.tagName);
    if (block && out && !out.endsWith("\n")) out += "\n";
    if (node.tagName === "LI") out += "- ";
    node.childNodes.forEach(walk);
    if (block && !out.endsWith("\n")) out += "\n";
  };
  doc.body.childNodes.forEach(walk);
  return out
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * An onPaste handler for a textarea: rich text with links goes in with the links kept, at the
 * cursor. Anything else pastes as usual. `onText` gets the new value.
 */
export function pasteKeepingLinks(onText: (value: string) => void) {
  return (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const html = e.clipboardData.getData("text/html");
    const text = html ? htmlToTextWithLinks(html) : null;
    if (text === null) return;
    e.preventDefault();
    const el = e.currentTarget;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    onText(el.value.slice(0, start) + text + el.value.slice(end));
  };
}
