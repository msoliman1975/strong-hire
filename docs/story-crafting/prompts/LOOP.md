# Deep story crafting: loop driver

You are the one session that builds RMAP-8, deep story crafting, end to end and unattended. You
write the code yourself, one task at a time, in the order of
`docs/story-crafting/execution-plan.md`. Every wake-up you read this file and do the next step.

## Authority the user gave you (do not ask again)

The user started this session to run unattended and gave these permissions up front:

- Create and push branches named `feat/sc-<NN>-<slug>` (from the plan), commit to them, and
  force-push only to those branches when a rebase needs it.
- Open pull requests from those branches into `main`, mark them ready, turn on **auto-merge with
  squash** for them, subscribe to their activity, and fix their CI and review comments.
- Decide anything the spec leaves open, using the precedence in `00-common.md`. Record each
  decision in the PR description under "Decisions".

Never ask the user a question and never wait for an answer. Never do any of these:

- push to `main`, or merge or approve a PR by hand;
- change repository settings, deploy, or use production secrets;
- skip or disable a test;
- edit a migration that is already on `main`.

## How you are started

The user opens a new cloud session on `msoliman1975/strong-hire` with the permission mode set to
**Auto**, and types:

```text
/loop Read docs/story-crafting/prompts/LOOP.md and do the next step.
```

`/loop` without an interval lets you pace yourself: after each turn you schedule your next
wake-up.

If `docs/story-crafting/` is not on `main` yet, read this file from the design branch:

```bash
git fetch origin claude/confident-keller-wko1r5
```

```bash
git show origin/claude/confident-keller-wko1r5:docs/story-crafting/prompts/LOOP.md
```

Your first task, SC00, then brings `docs/story-crafting-spec.md`, `docs/story-crafting/` and the
roadmap entries onto `main`.

## Your memory

- Keep a log in `.claude/sc-build-log.md`. It is untracked: never commit it. Read it first on
  every wake-up. Each entry has:
  - the time and the task;
  - what changed;
  - the PR link and its state;
  - what is next;
  - decisions and blockers.
- The container can restart and lose the log. GitHub is the real record: a task is done only when
  its PR is merged into `main`. If the log is missing, rebuild it from the merged and open PRs
  whose head branch starts with `feat/sc-` (GitHub MCP tools `list_pull_requests` and
  `pull_request_read`).

## Every wake-up

1. **Read** the log, then the PRs on `feat/sc-*` branches. Note which tasks are merged, which PR
   is open and its CI state.
2. **First wake-up only, preflight:**
   - `git fetch origin main`, then work from a clean checkout of `origin/main`.
   - Install once: `uv sync --all-packages` and `pnpm --dir apps/web install`. Note in the log the
     commands that work in this container.
   - Find out whether auto-merge works: when you open the SC00 PR, call `enable_pr_auto_merge`
     (squash). If GitHub refuses (auto-merge not allowed on the repo, or `main` has no required
     checks), switch to **stacked mode** for the whole run:
     - each next task branches from the previous task's branch instead of `main`;
     - every PR still targets `main`;
     - the final report lists the merge order.

     Log which mode you are in.
   - Auto-merge can stay pending even with CI green and the PR clean; this happened on this repo
     before. If a PR has green CI, is mergeable and is still open 10 minutes after its last check
     finished, note it in the log as "waiting for the owner to merge". Then continue with the next
     task whose dependencies allow it, in stacked mode if needed. Do not merge it yourself.
3. **An open task PR exists:**
   - **CI failing:** check out its branch, reproduce the failure locally, fix it, run the checks,
     push. Keep each fix to what the failure needs. After three failed attempts at the same
     failure, mark the task BLOCKED (step 6).
   - **Review comments from the user:** address each one and reply in the thread with what you did.
     GitHub replies end with the attribution footer from your system prompt.
   - **CI green and auto-merge on:** nothing to do for it. Go to step 4 if another task can start,
     else end the turn.
   - **Merged:** log it as done and go to step 4.
4. **Start or continue a task.** The next task is the first one in the plan that is not merged and
   whose "Waits for" tasks are all merged into `main`. In stacked mode, it is the first one whose
   dependencies all have a finished PR. At most two task PRs may be open at once, and never two
   that touch the same folders.
   - Read `00-common.md`, then the task's prompt file (`prompts/SC<NN>-*.md`), then the spec
     sections it names.
   - New task: create its branch from `origin/main` (stacked mode: from the previous task's
     branch). Open a **draft** PR early with the template in `00-common.md`, and subscribe to it
     (`subscribe_pr_activity`) so CI and review events wake you.
   - Work as far as this turn allows. Commit in small, green steps and push often, so a restart
     loses nothing. Update the checklist in the PR description as you go.
   - Finished means:
     - every "Done when" item in the task prompt is true;
     - the full local checks pass;
     - the screen check in `00-common.md` is done for every screen the task owns.

     Then mark the PR ready for review, turn on auto-merge with squash, and log it.
5. **Schedule the next wake-up** (dynamic `/loop`):
   - about 4 minutes while CI runs on a PR you just pushed;
   - about 1 minute when you stopped mid-task only because the turn got long;
   - 20 minutes as a fallback.

   PR activity events also wake you.
6. **Blocked.** A task is blocked by a secret, a paid hosted model run, a missing service, or the
   same CI failure three times. Then:
   - write "BLOCKED: <one line>" at the top of the log and in the PR description;
   - leave the PR as a draft;
   - move on to the next task that does not depend on it.

   If no task can move, end the loop (`ScheduleWakeup` with `stop: true`) with a one-line summary
   that starts "BLOCKED:".
7. **Finished.** When SC08 has merged:
   - write the final report at the top of the log: every requirement ID with its test, every PR
     with its link, every decision;
   - post the same report as a comment on the SC08 PR;
   - end the loop with `stop: true`.

## Never

- Build a task out of order, or start one whose dependencies have not merged (outside stacked
  mode).
- Mark a task done before its PR is merged into `main` on GitHub.
- Let Strova add a fact the user did not give (CO-9 and SC-15). In tests, never invent model
  output: add fake fixtures as `CLAUDE.md` says.
- Break a reader of the legacy story columns: the interviewer, scorer, story fit, debrief,
  suggestions and versions (SC-14).
