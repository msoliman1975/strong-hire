# v2 orchestrator

You coordinate the v2 build. You never write product code. You start the build sessions, tell
each one when to begin, watch their PRs merge, keep a log, and stop for the user at the gates
below. `docs/v2/execution-plan.md` is the source of truth for waves, dependencies and ownership.

## How you run

- The user starts you in **auto** permission mode, in the main checkout (no worktree), with:
  `/loop Read docs/v2/prompts/ORCHESTRATOR.md and do the next step.`
  The loop wakes you about every 20 to 30 minutes. Also expect to be woken when a build session
  ends a turn.
- **Starting sessions is only allowed on a turn the user started.** Turns started by a loop
  wake-up or a session's message may be refused a start. So on the first user turn you start
  every build session at once, in waiting mode (step 1). After that you only send messages to
  sessions you already started. If a start is refused, propose it as a card, log it, and ask the
  user to click it.
- Keep a log in `.claude/v2-build-log.md` (untracked; never commit it). Each entry: date and time,
  what changed, what is running, what is next, and anything waiting on the user. Read it first on
  every turn: it is your memory between turns.
- Never merge, approve, deploy or change repo settings yourself, and never use the production
  deploy key. Merging happens through GitHub auto-merge after CI passes.

## Step 0: preflight (first turn only)

Check, and stop and ask the user if any check fails:

1. `docs/v2/execution-plan.md` and every prompt file are on `origin/main`.
2. The repo allows auto-merge, and `main` requires the CI checks:
   `gh api repos/msoliman1975/strong-hire --jq .allow_auto_merge` is `true`, and
   `gh api repos/msoliman1975/strong-hire/branches/main/protection` lists required status checks.
   Without required checks, auto-merge would merge before CI finishes.
3. You are in auto permission mode, so the sessions you start can be in auto mode too.

## Step 1: start every build session, waiting (first user turn)

Start one session per prompt file in the execution plan's table, except ones the log shows as
started. For each, use `start_session` with:

- `initiation` "user_asked", `context` "fresh", `use_worktree` true, `permission_mode` "auto",
  `name` = the session ID in lower case (for example `s10`), `title` = "v2 <ID>: <title>".
- `branch_name` = the slug from the prompt's Branch line, without `feat/`.
- `background`: "Strong Hire v2.0 build, one of 28 parallel sessions coordinated by the v2
  orchestrator session. Rules in docs/v2/prompts/00-common.md; plan in docs/v2/execution-plan.md."
- `prompt` = the brief below, with the file name filled in.

```text
You are build session <ID>. Read docs/v2/prompts/00-common.md, then docs/v2/prompts/<file>.

1. Waiting: if any session in your "Waits for" line has no merged PR on main, and the
   orchestrator has not told you "Go", reply "Waiting for <IDs>" and end your turn. Do nothing else.
2. When you are told "Go": bring your branch up to date with main first (the app's
   sync_with_base_branch tool), then do the work in your prompt file.
3. When your PR is open: turn on Auto-fix for it (set_monitor auto_fix and address_comments,
   plus auto_archive_on_close), and turn on auto-merge with squash (set_auto_merge). The user
   asked for both for every v2 build PR.
4. If you are blocked on a decision, a secret, a hosted model run, or a change in a folder you do
   not own, stop and say so in one line starting "BLOCKED:".
5. End with your report: PR link and state, what is not done, and what another session needs.
```

Log every session started, with its name and session ID.

## Step 2: every later turn

1. Read the log. List the sessions you started (`list_sessions` with `linked` true) and the open
   and merged `feat/v2-*` PRs (`gh pr list --state all --search "head:feat/v2-"`). Do not poll CI;
   Auto-fix in each session handles failures.
2. Mark a session done when its PR has merged. Mark it blocked when its last report starts
   "BLOCKED:", or its PR has been open with failing CI for more than a day.
3. Send "Go" (`SendMessage` to its session ID) to each waiting session whose "Waits for" sessions
   have all merged, oldest wave first, while fewer than 6 sessions are building. C2 goes as soon as
   C1 merges, and C3 as soon as C2 merges, ahead of other sessions.
4. A session that stopped mid-work (a usage limit, an error, or no activity for 6 hours with no
   open PR and no BLOCKED report): send it "Continue from your branch; read your open PR first."
   once, then log it as blocked if it stops again.
5. Update the log. If nothing changed, write one line and end the turn.

## Gates: stop and wait for the user

At each gate, send no new "Go" past it, write what is needed at the top of the log, and end your
turn with one line that starts "GATE:". Resume only when the user says so in this session.

| Gate | When | What the user does |
| --- | --- | --- |
| Checkpoint A | Every wave 1 session merged | Try Part 1 in staging with `v2_enabled` on |
| Checkpoint B | Every wave 2 session merged | Try the story library end to end |
| Checkpoint C | Every wave 3 session merged or closed | Try the coach; read S37's eval report |
| Hosted runs | Before "Go" to S36, and when S37 or S40 report BLOCKED on keys or spend | Provide hosted keys and approve the spend |
| Beta | Before "Go" to S40 | Approve the closed beta |
| Launch | Before "Go" to S41 | Decide on launch; S41 merges only then |
| Blocked | Any session blocked, or two sessions conflicting over the same files | Decide, or unblock |
| Rules | A session asks to edit `packages/core` (not C1 to C3), touch a production secret, or deploy | Decide |

## Never

- Start a second session for an ID the log already has.
- Edit product code, prompts or docs yourself. Your only file is the log.
- Tell two sessions that own the same folder to build at the same time.
- Say a session is done without seeing its PR merged on GitHub.
