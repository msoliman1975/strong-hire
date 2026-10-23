/** Light or dark theme. Follows the system until the admin picks one; the choice is per browser. */
export type Theme = "light" | "dark";

const KEY = "strong-hire-admin-theme";

export function savedTheme(): Theme | null {
  try {
    const value = globalThis.localStorage?.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function systemTheme(): Theme {
  return globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme | null): void {
  const root = document.documentElement;
  if (theme) root.dataset.theme = theme;
  else delete root.dataset.theme;
  try {
    if (theme) globalThis.localStorage?.setItem(KEY, theme);
    else globalThis.localStorage?.removeItem(KEY);
  } catch {
    // Storage can be blocked; the theme still applies to this page load.
  }
}
