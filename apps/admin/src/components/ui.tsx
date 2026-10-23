import { useEffect, useRef, type ReactNode } from "react";

/**
 * Page heading. Sets the document title and moves focus to the heading when the page opens,
 * so screen reader users hear where they are after each route change.
 */
export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} | Strong Hire Admin`;
    ref.current?.focus();
  }, [title]);
  return (
    <header className="page-head">
      <h1 ref={ref} tabIndex={-1}>
        {title}
      </h1>
      {children}
    </header>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="loading" role="status">
      {label}
    </p>
  );
}

export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="notice notice--error" role="alert">
      {title && <p className="label">{title}</p>}
      <p>{message}</p>
    </div>
  );
}
