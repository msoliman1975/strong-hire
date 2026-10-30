# UX with Strova: rules for every task

Read this file, then your task's prompt file. The task prompt names its branch, dependencies,
folders and requirement IDs.

## Sources and precedence

1. `docs/ux-strova/ux-spec.md`: the approved behaviour, data and rules, and the requirement IDs.
2. `docs/ux-strova/reference/mockups.html`: the approved screens. **Layout, copy, colours, order
   and states must match it.** Each screen is a hash route (`#home`, `#interview`, …); the task
   prompt lists the ones you own. Sample data in it is illustration only.
3. `docs/spec.md` and `CLAUDE.md`: everything else, including the gateway rule, the fake-model
   rule, contracts and schemas, migrations, and folder ownership.

When the spec and mockups differ, the mockups win for what the user sees and the spec wins for
behaviour and data. When neither answers a question, choose what is closest to the mockups and
the principles in section 1 of the spec, write the choice under "Decisions" in your PR, and carry
on. Never stop to ask.

## Product rules that apply everywhere

- Everything new replaces the current v2 screens behind `v2_enabled` (FL-1). v1 screens and v1
  behaviour do not change.
- Words: resume (never CV in user-facing copy), take, Realistic mode and Practice mode (stored mode
  value `coach` unchanged), Strova. Strova speaks in the first person; the interface refers to her
  in the third person.
- Use the existing v2 tokens in `apps/web/src/theme/tokens.css` and the v2 components. Do not add
  a new colour unless the mockup uses it; then add it as a token.
- Use the `Strova` component (U02) for every avatar. Pick the mode and size the spec gives for that
  place (spec section 4.3).
- Collapsible sections use `<details>`/`<summary>` (or an equivalent with `aria-expanded`), closed
  by default where the mockup shows them closed, with counts visible when closed.
- Accessibility: real buttons and links, labels on inputs, visible focus, WCAG AA contrast,
  `prefers-reduced-motion` respected.
- No real model or network call in any test. New model behaviour gets a prompt via `load_prompt`, a
  fake fixture, and a contract.

## The fidelity check (every screen you own)

Do this before you mark a PR ready, and again after any visual change:

1. Run the web app with mocks: `VITE_API_MOCKS=all pnpm --dir apps/web exec vite --port 5181`
   (in the background). Turn on `v2_enabled` in the mock store (see `apps/web/src/mocks/db.ts`,
   `OPEN_STATUS` and the localStorage key) and sign in with the dev login.
2. With Playwright (preinstalled: `require('playwright')`, `chromium.launch()`), screenshot the
   mockup screen (`file://<repo>/docs/ux-strova/reference/mockups.html#<route>`; clear its
   localStorage key `sh-mockups` first) and your app screen, both at 1280×900 and at 390×844.
3. Look at both images. Fix every difference in order, hierarchy, copy, colour, spacing scale,
   icons and states, except sample data and differences the real data causes.
4. Check the screen's other states that the mockup shows (empty, collapsed and expanded, before
   and after an action) the same way.
5. List the screens and states you checked in the PR description.

Add or update MSW handlers in `apps/web/src/mocks/` for every new endpoint, so the mock-mode app
works end to end. U12's Playwright journey runs on these mocks.

## Checks before every push

```bash
uv run ruff check .
```

```bash
uv run mypy
```

```bash
MODEL_PROFILE=fake uv run pytest -q
```

```bash
pnpm --dir apps/web lint
```

```bash
pnpm --dir apps/web typecheck
```

```bash
pnpm --dir apps/web test
```

After any contract change, regenerate `schemas/` the way `scripts/dev.ps1 schemas` does (read that
script for the underlying `uv run` command) and commit the result, and regenerate the web API types
if the OpenAPI schema changed (`apps/web` script `gen:api`; read how the repo produces
`openapi.json`). If Postgres 16 is available in the container, run the migration round trip
(upgrade, `alembic check`, downgrade to base, upgrade); otherwise CI runs it. Do not add bash-only
scripts to the repo (the developer machine is Windows).

## Tests and requirement IDs

Every requirement ID your task lists gets at least one test with the ID in its name or docstring.
Update existing tests that the redesign changes (for example the v2 plan page and Home tests): do
not delete coverage of an older requirement ID without moving it to the screen that now owns it.

## PR template

Title: `UX with Strova U<NN>: <task title> (<IDs>)`

```markdown
## What
One paragraph.

## Requirement IDs
- XX-1: test name
- …

## Screens checked against the mockups
- #route: 1280 and 390, states …

## Decisions
- …

## Checklist
- [ ] Done-when items from the task prompt
- [ ] ruff, mypy, pytest, web lint, typecheck, test
- [ ] Schemas regenerated (if contracts changed)
```

End the PR description with the attribution lines from your system prompt.

## Commits

Small, green commits with clear messages, each ending with the attribution lines from your system
prompt. Never commit secrets, the build log, screenshots, or `node_modules`.
