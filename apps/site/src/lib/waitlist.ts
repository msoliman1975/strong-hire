/** Client code for the waitlist form. Posts JSON to /api/public/waitlist (always 202 on success). */

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function utmSource(): string | null {
  const v = new URLSearchParams(location.search).get("utm_source");
  return v ? v.slice(0, 100) : null;
}

export function initWaitlistForms(): void {
  document.querySelectorAll<HTMLElement>("[data-waitlist]").forEach((root) => {
    const form = root.querySelector("form");
    if (!form || form.dataset.ready) return;
    form.dataset.ready = "1";
    const errorBox = root.querySelector<HTMLElement>("[data-error]")!;
    const done = root.querySelector<HTMLElement>("[data-done]")!;
    const button = form.querySelector<HTMLButtonElement>('button[type="submit"]')!;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = new FormData(form);
      const email = String(data.get("email") ?? "").trim();
      const when = data.get("interview_within");
      const emailInput = form.querySelector<HTMLInputElement>('input[name="email"]')!;
      const emailError = document.getElementById(`${form.id}-email-error`)!;
      const whenError = document.getElementById(`${form.id}-when-error`)!;

      const emailOk = EMAIL.test(email);
      emailError.hidden = emailOk;
      emailInput.setAttribute("aria-invalid", emailOk ? "false" : "true");
      whenError.hidden = Boolean(when);
      if (!emailOk) return emailInput.focus();
      if (!when) return form.querySelector<HTMLInputElement>('input[name="interview_within"]')?.focus();

      errorBox.hidden = true;
      button.disabled = true;
      try {
        const res = await fetch("/api/public/waitlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            interview_within: when,
            role_family: data.get("role_family") || null,
            marketing_consent: data.get("marketing_consent") === "on",
            source: utmSource(),
            website: String(data.get("website") ?? "") || null,
          }),
        });
        if (res.status === 202 || res.ok) {
          form.hidden = true;
          done.hidden = false;
          done.focus();
          return;
        }
        errorBox.textContent =
          res.status === 429
            ? "Too many tries from this network. Please wait an hour and try again."
            : res.status === 422
              ? "Something in the form isn't right. Check your email address and try again."
              : "We couldn't add you just now. Please try again in a few minutes.";
      } catch {
        errorBox.textContent = "We couldn't reach the server. Check your connection and try again.";
      } finally {
        button.disabled = false;
      }
      errorBox.hidden = false;
    });
  });
}

/** Q14: pass utm_* tags through to app links, so the sign-up funnel shows where people came from. */
export function passUtmToAppLinks(appUrl: string): void {
  const params = new URLSearchParams(location.search);
  const utm = [...params.entries()].filter(([k]) => k.startsWith("utm_"));
  if (utm.length === 0) return;
  document.querySelectorAll<HTMLAnchorElement>(`a[href^="${appUrl}"]`).forEach((a) => {
    const url = new URL(a.href);
    for (const [k, v] of utm) url.searchParams.set(k, v);
    a.href = url.toString();
  });
}
