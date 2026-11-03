# Resume screens redesign: loop driver

You are the one session that builds RMAP-9, the resume screens redesign, end to end and
unattended. You write the code yourself, one task at a time, in the order of
`docs/resume-screens/execution-plan.md`. Every wake-up you read this file and do the next step.

## Authority the user gave you (do not ask again)

The user started this session to run unattended and gave these permissions up front:

- Create and push branches named `feat/rs-<NN>-<slug>` (from the plan), commit to them, and
  force-push only to those branches when a rebase needs it.
- Open pull requests from those branches into `main`, mark them ready, turn on **auto-merge with
  squash** for them, subscribe to their activity, and fix their CI and review comments.
- Decide anything the spec leaves open, using the precedence in `00-common.md`. Record each
  decision in the PR description under "Decisions".

Never ask the user a question and never wait for an answer. Never do any of these:

- push to `main`, or merge or approve a PR by hand;
- change repository settings, deploy, or use production secrets;
- skip or disable a test;
- change `packages/core`, the API or a migration (spec D-8).

## How you are started

The user opens a new cloud session on `msoliman1975/strong-hire` with the permission mode set to
**Auto**, and types:

```text
/loop Read docs/resume-screens/prompts/LOOP.md and do the next step.
```

If `docs/resume-screens/` is not on `main` yet, read this file from the design branch:

```bash
git fetch origin claude/festive-albattani-kugrfd
```

```bash
git show origin/claude/festive-albattani-kugrfd:docs/resume-screens/prompts/LOOP.md
```

Your first task, RS00, then brings `docs/resume-screens/` and the roadmap entry onto `main`.

## Your memory

- Keep a log in `.claude/rs-build-log.md`. It is untracked: never commit it. Read it first on
  every wake-up. Each entry has the time and task, what changed, the PR link and state, what is
  next, and any decisions or blockers.
- GitHub is the real record: a task is done only when its PR is merged into `main`. If the log is
  missing, rebuild it from the PRs whose head branch starts with `feat/rs-` (GitHub MCP tools
  `list_pull_requests` and `pull_request_read`).

## Every wake-up

1. **Read** the log, then the PRs on `feat/rs-*` branches. Note which tasks are merged, which PRs
   are open, and their CI state.
2. **First wake-up only, preflight:**
   - Run `git fetch origin main`, then work from a clean checkout of `origin/main`.
   - Install once with `pnpm --dir apps/web install`. Add `uv sync --all-packages` only if a task
     needs it. Log the commands that work.
   - Find out whether auto-merge works: when you open the RS00 PR, call `enable_pr_auto_merge`
     (squash). If GitHub refuses, switch to **stacked mode** for the whole run:
     - each next task branches from the previous task's branch;
     - every PR still targets `main`;
     - the final report lists the merge order.

     Log which mode you are in.
   - Auto-merge can stay pending even with CI green. If a PR has been green, mergeable and open
     for 10 minutes after its last check, log it as "waiting for the owner to merge". Continue
     with the next task the dependencies allow, in stacked mode if needed. Never merge it
     yourself.
3. **An open task PR exists:**
   - **CI failing:** check out its branch, reproduce the failure, fix it, run the checks, push.
     After three failed attempts at the same failure, mark the task BLOCKED (step 6).
   - **Review comments from the user:** address each one and reply in the thread with what you did.
     Replies end with the attribution footer from your system prompt.
   - **CI green and auto-merge on:** go to step 4 if another task can start, else end the turn.
   - **Merged:** log it as done and go to step 4.
4. **Start or continue a task.** The next task is the first one in the plan that is not merged and
   whose "Waits for" tasks are all merged. At most two task PRs may be open at once, and never two
   that touch the same folders.
   - Read `00-common.md`, the task's prompt file (`prompts/RS<NN>-*.md`), the spec sections it
     names, and its mockup board.
   - New task: create its branch, open a **draft** PR early with the template in `00-common.md`,
     and subscribe to it (`subscribe_pr_activity`).
   - Commit in small, green steps and push often. Keep the checklist in the PR description up to
     date.
   - Finished means:
     - every "Done when" item is true;
     - the checks pass;
     - the screen check is done.

     Then mark the PR ready, turn on auto-merge with squash, and log it.
5. **Schedule the next wake-up** (dynamic `/loop`): about 4 minutes while CI runs, about 1 minute
   when you stopped mid-task, and 20 minutes as a fallback. PR activity events also wake you.
6. **Blocked** (a missing service, or the same CI failure three times):
   - write "BLOCKED: <one line>" at the top of the log and in the PR;
   - leave the PR as a draft;
   - move on to a task that does not depend on it.

   If nothing can move, end the loop (`ScheduleWakeup` with `stop: true`) with a summary that
   starts "BLOCKED:".
7. **Finished.** When RS06 has merged:
   - write the final report at the top of the log: every RSD ID with its test, every PR with its
     link, every decision;
   - post the same report as a comment on the RS06 PR;
   - end the loop with `stop: true`.

## Never

- Build a task out of order, or start one whose dependencies have not merged (outside stacked
  mode).
- Mark a task done before its PR is merged into `main`.
- Build from mockup boards A, B or C.
- Leave a function from the gap report without a home: default, used-by roles, upload a new
  version, story ideas, line rewrites.
