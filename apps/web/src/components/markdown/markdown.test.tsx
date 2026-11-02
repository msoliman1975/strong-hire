/**
 * SC-18: light Markdown in the reply box and the slot editors: a toolbar, Ctrl+B and Ctrl+I,
 * rich-text paste, and a safe renderer (no HTML ever runs).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import { ReplyBox } from "../../pages/coach/ReplyBox";
import { htmlToMarkdown, list, Markdown, markdownKeys, MarkdownToolbar, wrap } from "./markdown";

describe("SC-18: rendering", () => {
  it("SC-18: bold, italic, bullet and numbered lists, and kept line breaks", () => {
    const { container } = render(
      <Markdown text={"I **led** the *rollout*.\nThen I wrote it up.\n\n- split by country\n- one week\n\n1. plan\n2. ship"} />,
    );
    expect(container.querySelector("strong")).toHaveTextContent("led");
    expect(container.querySelector("em")).toHaveTextContent("rollout");
    expect(container.querySelector("br")).not.toBeNull();
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
  });

  it("SC-18: raw HTML is shown as text, never run", () => {
    const { container } = render(<Markdown text={'<img src=x onerror="alert(1)"> **hi** <script>x()</script>'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container).toHaveTextContent('<img src=x onerror="alert(1)"> hi <script>x()</script>');
  });

  it("SC-18: snake_case words and lone stars stay as they are", () => {
    const { container } = render(<Markdown text="the user_id column and 2 * 3" />);
    expect(container.querySelector("em")).toBeNull();
    expect(container).toHaveTextContent("the user_id column and 2 * 3");
  });
});

describe("SC-18: editing", () => {
  it("SC-18: wrap and unwrap the selection; make and undo lists", () => {
    expect(wrap("I led it", 2, 5, "**")).toEqual({ value: "I **led** it", start: 4, end: 7 });
    expect(wrap("I **led** it", 4, 7, "**")).toEqual({ value: "I led it", start: 2, end: 5 });
    expect(list("plan\nship", 0, 9, "number").value).toBe("1. plan\n2. ship");
    expect(list("- plan\n- ship", 0, 13, "bullet").value).toBe("plan\nship");
  });

  it("SC-18: pasted rich text becomes Markdown", () => {
    expect(htmlToMarkdown("<p>I <b>led</b> the <em>move</em>.</p><ul><li>one</li><li>two</li></ul><ol><li>a</li><li>b</li></ol>")).toBe(
      "I **led** the *move*.\n\n- one\n- two\n\n1. a\n2. b",
    );
    expect(htmlToMarkdown('<span style="font-weight:700">Bold</span> and <script>x()</script>plain')).toBe("**Bold** and x()plain");
  });

  function Field() {
    const [value, setValue] = useState("I led the move");
    const ref = useRef<HTMLTextAreaElement>(null);
    const keys = markdownKeys(setValue);
    return (
      <>
        <MarkdownToolbar target={ref} onChange={setValue} />
        <label htmlFor="f">Text</label>
        <textarea id="f" ref={ref} value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={keys.onKeyDown} onPaste={keys.onPaste} />
      </>
    );
  }

  it("SC-18: the toolbar and Ctrl+B / Ctrl+I format the selected words", async () => {
    render(<Field />);
    const box = screen.getByLabelText("Text") as HTMLTextAreaElement;
    box.setSelectionRange(2, 5);
    await userEvent.click(screen.getByRole("button", { name: "Bold" }));
    expect(box.value).toBe("I **led** the move");
    box.setSelectionRange(14, 18);
    fireEvent.keyDown(box, { key: "i", ctrlKey: true });
    expect(box.value).toBe("I **led** the *move*");
    box.setSelectionRange(0, box.value.length);
    await userEvent.click(screen.getByRole("button", { name: "Bulleted list" }));
    expect(box.value).toBe("- I **led** the *move*");
    expect(screen.getByRole("toolbar", { name: "Formatting" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-keyshortcuts", "Control+B");
  });

  it("SC-18: pasting rich text into a field inserts Markdown", () => {
    render(<Field />);
    const box = screen.getByLabelText("Text") as HTMLTextAreaElement;
    box.setSelectionRange(box.value.length, box.value.length);
    fireEvent.paste(box, { clipboardData: { getData: (t: string) => (t === "text/html" ? "<b>fast</b>" : "fast") } });
    expect(box.value).toBe("I led the move**fast**");
  });

  it("SC-18: the reply box has the formatting toolbar, and Ctrl+B does not send", async () => {
    const sent: string[] = [];
    function Box() {
      const [value, setValue] = useState("");
      return <ReplyBox value={value} onChange={setValue} onSend={() => sent.push(value)} onQuick={() => undefined} busy={false} quick={false} />;
    }
    render(<Box />);
    expect(screen.getAllByRole("toolbar", { name: "Formatting" })[0]).toBeInTheDocument();
    const box = screen.getByLabelText("Your reply") as HTMLTextAreaElement;
    await userEvent.type(box, "I led it");
    box.setSelectionRange(2, 5);
    fireEvent.keyDown(box, { key: "b", ctrlKey: true });
    expect(box.value).toBe("I **led** it");
    expect(sent).toEqual([]);
  });
});
