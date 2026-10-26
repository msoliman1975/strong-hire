// L04: sends the waitlist form to POST /api/public/waitlist (same origin; Caddy proxies only
// /api/public/* on the site host). The answer is always "check_email", whether or not the
// address was already on the list. A plain file, so the strict CSP allows it (script-src 'self').
(() => {
  const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const source = new URLSearchParams(location.search).get("utm_source");

  for (const form of document.querySelectorAll("form[data-waitlist]")) {
    const card = form.parentElement;
    const done = card.querySelector("[data-done]");
    const show = (name, on) => {
      const el = form.querySelector(`[data-error="${name}"]`);
      if (el) el.hidden = !on;
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const email = String(data.get("email") || "").trim();
      const when = data.get("interview_within");
      const emailOk = EMAIL_RE.test(email);
      show("email", !emailOk);
      show("interview_within", !when);
      show("server", false);
      form.querySelector('[name="email"]').setAttribute("aria-invalid", emailOk ? "false" : "true");
      if (!emailOk || !when) return;

      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const response = await fetch("/api/public/waitlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            interview_within: when,
            role_family: data.get("role_family") || null,
            marketing_consent: data.get("marketing_consent") === "on",
            source: source ? source.slice(0, 100) : "site",
            website: data.get("website") || null,
          }),
        });
        if (!response.ok) throw new Error(String(response.status));
        form.hidden = true;
        done.hidden = false;
        done.focus();
      } catch {
        show("server", true);
      } finally {
        button.disabled = false;
      }
    });
  }
})();
