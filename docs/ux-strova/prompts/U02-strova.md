# U02 · Strova component

- **Branch:** `feat/ux-u02-strova`
- **Waits for:** U00.
- **Owns:** `apps/web/src/components/strova/` (new), its tests, and a dev preview route.
- **Requirement IDs:** SV-1 to SV-5.
- **Mockup:** `docs/ux-strova/reference/strova-avatar.html` (every mode and size), and the `strova(mode, size)` function and the `.sv-*` CSS in
  `docs/ux-strova/reference/mockups.html`; the canvas page "Strova avatar (approved)".

## Goal

One React component, `<Strova mode="coaching" size={72} hat?="coach|interviewer" />`, that renders
the approved avatar exactly, in every mode, with its animations.

## Build

1. Port the drawing from the mockup's `strova()` exactly: the same SVG paths, transforms
   (`translate(40 29.6) scale(1.2)` for hair and face), colours, mouths, brows, eyes, ring, zigzag
   ring path and the effects per mode. Render it as JSX, not as an HTML string.
2. Modes: `listening`, `speaking`, `interviewing`, `thinking`, `analysing`, `coaching`,
   `celebrating`. Colours by hat as in spec section 4.1; `thinking` takes the hat prop (default
   coach).
3. Clip-path ids must be unique per instance (`useId`).
4. Effects hidden below 64 px (SV-5). `role="img"` and an `aria-label` naming the state (SV-4).
5. Move the `.sv-*` keyframes (timings in spec section 4.3, exactly) into a CSS file next to the component; stop all of them under
   `prefers-reduced-motion: reduce`, with the tick drawn (SV-3).
6. A dev-only preview route (behind the existing dev routes) showing every mode at 160, 72, 40, 28
   and 18 px, so the fidelity check can screenshot it.

## Tests

- SV-1: each mode renders its expected parts (mouth shape, effect group present or absent).
- SV-2: ring colour per hat; zigzag path for thinking and analysing.
- SV-3: the reduced-motion rule exists in the CSS (a unit test that reads the CSS text is fine).
- SV-4: the accessible label per mode.
- SV-5: no effect group at size 40, effect group at size 72.

## Done when

Tests pass, and the preview route matches `reference/strova-avatar.html` side by side at the same
sizes and in motion (fidelity check). Also export a 64 px PNG of the coaching mode to
`apps/web/public/strova/strova-coaching-64.png` (and a 128 px one) for emails and the site.
