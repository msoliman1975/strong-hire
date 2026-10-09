# Test server (Hetzner)

One Hetzner cloud server runs the whole stack for the test release, with the `claude` model profile.
Claude Haiku 5.5 and Claude Sonnet 5.5 answer the text roles. Speech-to-text (faster-whisper) and
text-to-speech (Kokoro) run on the server CPU.

| Item | Value |
| --- | --- |
| Server | `stronghire-test`, type cx43 (8 vCPU shared, 16 GB, 160 GB disk), Nuremberg (nbg1) |
| Cost | $18.49 per month, billed by the hour while the server exists |
| Address | `https://getstronghire.com` (web and `/api`), `https://rtc.getstronghire.com` (LiveKit) |
| Firewall | Hetzner firewall `stronghire-fw`: 22, 80, 443/tcp, 443/udp, 7881/tcp, 7882/udp |
| Repo on the server | `/opt/stronghire/strong-hire`, read-only deploy key |
| Anthropic key | `/etc/stronghire/anthropic.key`, readable by root only, never in the repo or `.env` |

Note: the spec puts hosting in Hetzner's US region. US servers cost about 3.5 times more, so the
test release runs in Germany. Expect about 100 ms more network time per voice turn for North
American users. Moving to the US region later is the same setup on a new server.

## How the stack runs

`scripts/profile.ps1` starts the stack, as on a laptop. When `.env` has `STACK_TARGET=server`, it
adds `infra/compose.server.yaml`, which:

- adds Caddy (`infra/docker/caddy.Dockerfile`). Caddy serves the production web build, sends
  `/api/*` to the API, and gets TLS certificates from Let's Encrypt.
- runs LiveKit in production mode with real keys (`infra/livekit/livekit.server.yaml`).
- runs the API in staging mode: no dev login, a real session secret, no code reload.
- publishes no ports except Caddy and LiveKit media. The API (8700) and LiteLLM (4000) listen on
  127.0.0.1 only, for the script's health check and LiteLLM key setup.

Sign-in uses email links. The server sends them through Brevo SMTP (`smtp-relay.brevo.com`, port 587). The domain is authenticated in Brevo with DKIM records in GoDaddy DNS. The SMTP key is in `/etc/stronghire/smtp.key` and in `.env`.

## First setup

1. In the domain's DNS, add two A records: `@` and `rtc`, both to the server IP.
2. SSH in as root. Check that cloud-init finished: `cloud-init status` says `done`.
3. Create a deploy key and add it to GitHub as read-only:
   `ssh-keygen -t ed25519 -N "" -f ~/.ssh/github` and
   `gh repo deploy-key add ~/.ssh/github.pub -R msoliman1975/strong-hire -t stronghire-test` (on your PC).
4. Clone: `GIT_SSH_COMMAND="ssh -i ~/.ssh/github" git clone git@github.com:msoliman1975/strong-hire.git /opt/stronghire/strong-hire`,
   then `git config core.sshCommand "ssh -i ~/.ssh/github"` in that folder.
5. Create `.env`: copy `.env.example`, append `infra/server/env.server.example`, and fill in every
   empty value. Generate secrets with `openssl rand -hex 32`.
6. Save the Anthropic key: `install -m 600 /dev/null /etc/stronghire/anthropic.key`, then write the key into it.
7. Start: `./scripts/server-deploy.sh`. The first run builds the images and downloads the speech
   models.
8. Load the launch companies once: `pwsh scripts/dev.ps1 seed`.

## Update to the latest main

```bash
cd /opt/stronghire/strong-hire && ./scripts/server-deploy.sh
```

### Deploy from the owner's PC

The deploy key (`infra/server/deploy-key.pub`) can start a deploy and nothing else. Its private
half is `~/.ssh/stronghire_deploy` on the owner's PC. To add it on the server, run once:
`bash infra/server/add-deploy-key.sh`. It writes the key into root's `authorized_keys` with
`command="…/scripts/server-deploy.sh",restrict`, so the server ignores any other command.

To deploy: `ssh -i ~/.ssh/stronghire_deploy root@getstronghire.com`. Claude Code has an allow
rule for this exact command. To change the key, replace `deploy-key.pub` and run the script again.

## Test plans

Stripe is not set up. `infra/server/grant-test-plans.sh` gives a test subscription (status active,
`TEST_PLAN_MINUTES` minutes, one year) to `TEST_PLAN_OWNER` and to the first `TEST_PLAN_SLOTS`
other people who sign up. Cron runs it every 5 minutes:

```bash
echo '*/5 * * * * root /opt/stronghire/strong-hire/infra/server/grant-test-plans.sh >> /var/log/stronghire-test-plans.log 2>&1' > /etc/cron.d/stronghire-test-plans
```

The rows have `stripe_customer_id` `test-plan:<user id>`. To remove them:
`delete from subscriptions where stripe_customer_id like 'test-plan:%';`

## Costs

- `pwsh scripts/profile.ps1 status` shows Claude spend today and this month.
- `.env` sets the limits: `CLAUDE_DAILY_BUDGET_USD`, `CLAUDE_MONTHLY_BUDGET_USD`, `CLAUDE_RPM_LIMIT`.
  Also set a monthly limit in the Anthropic Console. It is the hard limit.
- To pay nothing between test rounds, take a snapshot of the server in the Hetzner console, then
  delete the server. Hetzner bills a server that is powered off.

## Re-read stored CVs

After a change to the CV file reader (`apps/worker/src/strong_worker/inputs/documents.py`) or
to the resume prompt (`prompts/extractor/resume.v*.txt`), stored CVs keep the old parsed data
until they are read again. The command `strong_worker.inputs.reread` reads every stored CV file
again and runs the extractor:

- It skips deleted CVs (R1 `deleted_at`) and CVs without a stored file.
- It skips CVs the user confirmed on the "Check your CV" screen (`resumes.confirmed_at`). The
  user's version wins. `--include-confirmed` overwrites them too and clears `confirmed_at`, so
  those users see the screen again. Ask the users before you use it.
- Each update writes `resumes.parsed_json` and adds an `audit_logs` row with the action
  `resume.reread` (old and new role count, prompt version, flags).
- Gap reports made before the run keep their numbers. The next gap analysis uses the new data.

Each CV costs one extractor call (Claude Haiku), also with `--dry-run`. Run it in the worker
container. First a dry run on a few CVs, then the full run:

```bash
cd /opt/stronghire/strong-hire
docker exec -it "$(docker ps -qf name=worker)" python -m strong_worker.inputs.reread --dry-run --limit 5 --verbose
docker exec -it "$(docker ps -qf name=worker)" python -m strong_worker.inputs.reread
```

Other options: `--org <id>` and `--resume <id>` limit the run to one org or one CV. The command
prints the number of CVs per outcome: `updated`, `unchanged`, `skipped_confirmed`,
`unreadable`, `extraction_failed`, `error`.
