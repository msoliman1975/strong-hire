# Resume screens redesign: rules for every task

Read this file, then your task's prompt file. The task prompt names its branch, dependencies,
folders and requirement IDs.

## Sources and precedence

1. `docs/resume-screens/spec.md`: the gap report, decisions D-1 to D-10, and RSD-1 to RSD-16. The
   owner approved them; do not re-open them.
2. The approved mockups:
   - the canvas <https://claude.ai/artifact/Hi9y2agVNadm9cmKLwhmWt>, boards "Resumes list (2
     columns)", "Target roles (shared card shell)" and "Check C2: Guided, revised (v2)";
   - local copies in `docs/resume-screens/mockups/`.

   Match their order, copy, states and layout. Boards A, B and C are rejected.
3. The current v2 screens and `apps/web/src/components/ux/ux.css` (`sx-*`) for tokens, spacing,
   buttons, chips and cards. The mockups use literal hex values; in code use the `--sh-*` tokens
   from `apps/web/src/theme/tokens.css`. Never add a colour that is not a token.
4. `docs/spec.md` and `CLAUDE.md` cover everything else, including folder ownership and the
   commands.

When a question is still open, choose what is closest to the mockup and the existing v2 screens.
Write the choice under "Decisions" in your PR and carry on. Never stop to ask.

## Product rules that apply everywhere

- **One resume page (D-1).** After RS05 nothing links to `/resumes/:id` except the redirect.
- **The counts agree (D-4).** The list, the check page and Home use the same helpers
  (`resumeIssueCounts`, `checkResume`, the story-ideas query). Never compute a count a second way.
- **No backend change (D-8).** If a task seems to need one, stop that part. Log it under
  "Decisions" as a follow-up, and build the closest version without it.
- **Onboarding still works (D-9).** The check page opened with a `jobId` keeps the Steps header and
  "Continue to your interview plan". The v1 check page (`CheckResumePage`, no v2 flag) does not
  change.
- **Words:**
  - resume, never CV;
  - sentence case;
  - "Strova's findings" on the check page and "open issues" on the list tile;
  - Strova is referred to in the third person.
- **Accessibility:**
  - real buttons and links, with labels on inputs and icon buttons;
  - visible focus and WCAG AA contrast;
  - colour is never the only cue: the ▲ has a spoken label, and chips say their state in text;
  - drawers are modal dialogs: focus is trapped, Esc closes them, focus returns to the opener;
  - `prefers-reduced-motion` is respected.
- **No model or network call in any test.** The web tests run on MSW mocks.

## The screen check (every screen you own)

Do this before you mark a PR ready, and again after any visual change:

1. Run the web app with mocks: `VITE_API_MOCKS=all pnpm --dir apps/web exec vite --port 5181`, in
   the background. Turn on `v2_enabled` in the mock store, as `apps/web/e2e/strova.spec.ts` does,
   and sign in with the dev login.
2. With Playwright (preinstalled: `require('playwright')`, `chromium.launch()`), screenshot each
   screen and state you own at 1280×900 and at 390×844. Look at the images.
3. Compare them with the approved mockup:
   - order, copy, spacing and tokens;
   - every state named in your task prompt;
   - no horizontal scroll at 390.
4. Run axe (`@axe-core/playwright`, as `strova.spec.ts` does) on each screen, with no violations.
5. List the screens and states you checked in the PR description. Do not commit screenshots.

Keep the MSW handlers in `apps/web/src/mocks/` serving every state the screens need. For example,
the mock store needs:

- a default resume with high issues;
- a resume with none;
- a resume still being read;
- a resume used by 7 roles;
- a resume with line rewrites.

## Checks before every push

```bash
pnpm --dir apps/web lint
```

```bash
pnpm --dir apps/web typecheck
```

```bash
pnpm --dir apps/web test
```

If a task touched anything outside `apps/web` or `docs`, also run `uv run ruff check .`,
`uv run mypy` and `MODEL_PROFILE=fake uv run pytest -q`.

Do not add bash-only scripts to the repo; the developer machine is Windows.

## Tests and requirement IDs

Every requirement ID your task lists gets at least one test with the ID in its name, for example
`it("RSD-2: the open issues tile is amber with a spoken mark when an issue is high", …)`. Update the
tests the change affects: RM-1, RM-2, RM-3, RM-4, SG-6, IN-3, IN-12, TG-1 and RMAP-5. Move
coverage of an older ID to the code that now owns it; never just delete it.

## PR template

Title: `Resume screens RS<NN>: <task title> (<IDs>)`

```markdown
## What
One paragraph.

## Requirement IDs
- RS-x: test name
- …

## Screens checked
- screen: 1280 and 390, states …

## Decisions
- …

## Checklist
- [ ] Done-when items from the task prompt
- [ ] web lint, typecheck, test
- [ ] Screen check and axe at 1280 and 390
- [ ] Older IDs still covered (RM-*, SG-6, IN-12, TG-1, RMAP-5)
```

End the PR description with the attribution lines from your system prompt.

## Commits

Small, green commits with clear messages, each ending with the attribution lines from your system
prompt. Never commit secrets, the build log, screenshots or `node_modules`.
