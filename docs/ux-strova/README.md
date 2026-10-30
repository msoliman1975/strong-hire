# UX with Strova: build package

Everything a dedicated loop session needs to build the approved UX, unattended.

| File | What it is |
| --- | --- |
| `ux-spec.md` | The approved design: principles, concepts and words, Strova, every screen, the plan, suggestions, readiness, data changes, requirement IDs |
| `reference/mockups.html` | The approved clickable mockups, the visual and copy reference (open as a file; screens are hash routes) |
| `execution-plan.md` | The 14 tasks (U00 to U13), their order, branches, folders and requirement IDs |
| `prompts/LOOP.md` | The loop driver: what the session does on every wake-up |
| `prompts/00-common.md` | Rules for every task, including the fidelity check against the mockups |
| `prompts/U00-*.md` to `prompts/U13-*.md` | One prompt per task |
| `reference/strova-avatar.html` | Every Strova mode at every size, animated: the avatar reference |
| `settings.suggested.json` | An optional permissions allowlist you can copy to `.claude/settings.json` |

Published copies: mockups https://claude.ai/artifact/85ETi6z82XtAKXmS4wQ7tn · Strova avatar
https://claude.ai/artifact/KwPbVu6fzqAv3Kk4sGwv4J (page "Strova avatar (approved)").

## Before you launch (once)

1. **Auto-merge on GitHub.** In the repository settings, turn on "Allow auto-merge", and make sure
   the `main` branch protection requires the CI checks from `.github/workflows/ci.yml`. Without
   required checks, auto-merge would merge before CI finishes. If you skip this, the loop still
   runs, in "stacked mode": it opens every PR without merging, and you merge them in order at the
   end.
2. **Environment.** The cloud environment needs network access to install Python and web
   packages (PyPI, the npm registry) and GitHub access with push rights to this repository.
3. **Permissions.** Auto mode runs most tool calls without asking. To make sure the routine build
   commands never prompt, copy `docs/ux-strova/settings.suggested.json` to `.claude/settings.json`
   and commit it on `main` yourself (it allows `uv`, `pnpm`, `node`, `git`, a few read-only shell
   commands and the GitHub tools). This is your call: it applies to every session on this repo.

## Launch

1. Open a new Claude Code cloud session on `msoliman1975/strong-hire` (default branch).
2. Set the permission mode to **Auto** in the mode dropdown next to the prompt box.
3. Send exactly:

```text
/loop Read docs/ux-strova/prompts/LOOP.md and do the next step. If docs/ux-strova is not on main yet, read it from origin/claude/eloquent-pascal-7ygux4. You are authorized to create and push feat/ux-u* branches, open PRs into main, turn on auto-merge for them and fix their CI, without asking me.
```

## While it runs

- It works task by task (U00 to U13), one PR each, titled "UX with Strova U<NN>: …".
- To follow progress, watch those PRs, or ask the session "status?" at any time.
- To give feedback, comment on a PR. The session addresses comments on its next wake-up.
- To pause, interrupt the session. To stop, tell it to stop the loop.
- If it hits something only you can provide (a secret, a paid model run), it writes "BLOCKED:" in
  the PR and moves on to the next task it can do.
- When U13 merges, the session posts a final report on the U13 PR and stops.
