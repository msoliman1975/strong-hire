# Deep story crafting: rules for every task

Read this file, then your task's prompt file. The task prompt names its branch, dependencies,
folders and requirement IDs.

## Sources and precedence

1. `docs/story-crafting-spec.md`: decisions D-1 to D-14, the sections and slots table, SC-1 to
   SC-18 and the technical design. The owner agreed every decision there; do not re-open them.
2. `docs/ux-strova/ux-spec.md` and the current v2 screens: Career Stories, the coach session and
   the story page. There are no mockups for this project, so new screens follow the existing v2
   design: tokens, `sx-*` components, Strova's avatar and the copy rules.
3. `docs/spec.md` and `CLAUDE.md` cover everything else, including:
   - the gateway rule and the fake-model rule;
   - contracts and schemas, and migrations;
   - folder ownership.

When a question is still open, choose what is closest to the spec's decisions and the existing v2
screens. Write the choice under "Decisions" in your PR and carry on. Never stop to ask.

## Product rules that apply everywhere

- **The candidate owns the story (CO-9, D-6).** Strova may reword. Every fact, number, name, tool
  and result claim in Strova's text must come from the user's words. Every slot that Strova wrote
  carries verbatim `quotes`; slots the user typed are `by_user`.
- **Legacy columns are derived (D-12, SC-14).** Every outline write renders `context`, `stakes`,
  `action`, `result` and `reflection` in code, with no model call. Nothing that reads those
  columns changes.
- **Classic stories keep working.** A classic story (style null) uses today's turn, editor and
  review until the user organizes it (D-11). A v1 user never sees any of this.
- **Words:** resume (never CV), story, take, Strova. Section names: Situation, Task, Action,
  Result, Learning (STAR), and Challenge, Action, Result, Learning (CARL). Strova speaks in the
  first person; the interface refers to her in the third person.
- **No grading words in Strova's messages.** The rules of `prompts/coach/turn.v3.txt` still hold:
  - one question at a time;
  - no "good", "great", "strong" and similar;
  - no suggesting facts.
- **Accessibility:**
  - real buttons and links, with labels on inputs;
  - visible focus and WCAG AA contrast;
  - `prefers-reduced-motion` respected;
  - slot chips say their state in text, not only in colour.
- **No real model or network call in any test.** New model behaviour gets:
  - a prompt through `load_prompt`;
  - a contract in `strong_core.schemas`;
  - a fake fixture in `packages/core/src/strong_core/gateway/fixtures/coach/`.
- **Prompt refs:** store each prompt ref with what it produced, as the coach does today.

## The screen check (every screen you own)

Do this before you mark a PR ready, and again after any visual change:

1. Run the web app with mocks: `VITE_API_MOCKS=all pnpm --dir apps/web exec vite --port 5181`, in
   the background. Turn on `v2_enabled` in the mock store, as `apps/web/e2e/strova.spec.ts` does,
   and sign in with the dev login.
2. With Playwright (preinstalled: `require('playwright')`, `chromium.launch()`), screenshot each
   screen and state you own at 1280×900 and at 390×844. Look at the images.
3. Check against the spec and the neighbouring v2 screens:
   - the order and the copy;
   - the spacing scale and tokens;
   - Strova's avatar mode;
   - every state: empty, partly filled, Ready, skipped slot, flags, hints, error, loading;
   - no horizontal scroll at 390.
4. Run axe (`@axe-core/playwright`, as `strova.spec.ts` does) on each screen with no violations.
5. List the screens and states you checked in the PR description.

Add or update the MSW handlers in `apps/web/src/mocks/` for every new endpoint, so the mock-mode
app works end to end. SC08's journey runs on these mocks.

## Checks before every push

```bash
uv run ruff check .
```

```bash
uv run ruff format --check .
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

After any contract change:

- regenerate `schemas/` the way `scripts/dev.ps1 schemas` does (read that script for the
  underlying `uv run` command) and commit the result;
- regenerate the web API types if the OpenAPI schema changed (`apps/web` script `gen:api`; read
  how the repo produces `openapi.json`).

If Postgres 16 is available in the container, run the migration round trip: upgrade, `alembic
check`, downgrade to base, upgrade. Otherwise CI runs it.

Do not add bash-only scripts to the repo; the developer machine is Windows.

## Tests and requirement IDs

Every requirement ID your task lists gets at least one test with the ID in its name or docstring.
Update the existing tests that the change affects, such as the coach and stories tests (CO-*,
ST-*). Do not delete coverage of an older requirement ID without moving it to the code that now
owns it.

## PR template

Title: `Deep story crafting SC<NN>: <task title> (<IDs>)`

```markdown
## What
One paragraph.

## Requirement IDs
- SC-x: test name
- …

## Screens checked
- screen: 1280 and 390, states …

## Decisions
- …

## Checklist
- [ ] Done-when items from the task prompt
- [ ] ruff, mypy, pytest, web lint, typecheck, test
- [ ] Schemas regenerated (if contracts changed)
- [ ] Legacy columns still rendered and read the same (SC-14)
```

End the PR description with the attribution lines from your system prompt.

## Commits

Small, green commits with clear messages, each ending with the attribution lines from your system
prompt. Never commit secrets, the build log, screenshots or `node_modules`.
