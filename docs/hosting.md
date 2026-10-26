# Test server (Hetzner)

One Hetzner cloud server runs the whole stack for the test release, with the `claude` model profile.
Claude Haiku 5.5 and Claude Sonnet 5.5 answer the text roles. Speech-to-text (faster-whisper) and
text-to-speech (Kokoro) run on the server CPU.

| Item | Value |
| --- | --- |
| Server | `stronghire-test`, type cx43 (8 vCPU shared, 16 GB, 160 GB disk), Nuremberg (nbg1) |
| Cost | $18.49 per month, billed by the hour while the server exists |
| Address | `https://app.getstronghire.com` (web and `/api`; sign-in, Google and email links return here. `https://getstronghire.com` serves the same app until the marketing site takes it), `https://admin.getstronghire.com` (admin app and its own `/api`), `https://rtc.getstronghire.com` (LiveKit), `https://www.getstronghire.com` (marketing site preview, L04) |
| Firewall | Hetzner firewall `stronghire-fw`: 22, 80, 443/tcp, 443/udp, 7881/tcp, 7882/udp |
| Repo on the server | `/opt/stronghire/strong-hire`, read-only deploy key |
| Anthropic key | `/etc/stronghire/anthropic.key`, readable by root only, never in the repo or `.env` |

Hosting stays in Germany (decided Oct 26, 2026). US servers cost about 3.5 times more. Expect about
100 ms more network time per voice turn for North American users; the L08 load test checks that the
median voice turn stays under 800 ms from a North American client. If it does not, the fix is a
closer TURN or speech-to-text region, not moving the servers.

## How the stack runs

`scripts/profile.ps1` starts the stack, as on a laptop. When `.env` has `STACK_TARGET=server`, it
adds `infra/compose.server.yaml`, which:

- adds Caddy (`infra/docker/caddy.Dockerfile`). Caddy serves the production web build, sends
  `/api/*` to the API, and gets TLS certificates from Let's Encrypt. On the main host it answers
  404 to `/api/admin/*`, so the candidate origin never reaches admin routes.
- serves the admin app (`apps/admin`, D-1) on `admin.$DOMAIN`, from its own build in
  `/srv-admin`, with its own `/api/*` proxy and strict headers (CSP `default-src 'self'`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; AA-9). The session cookie is
  host-only, so signing in to one host does not sign you in to the other.
- runs LiveKit in production mode with real keys (`infra/livekit/livekit.server.yaml`).
- runs the API in staging mode: no dev login, a real session secret, no code reload.
- publishes no ports except Caddy and LiveKit media. The API (8700) and LiteLLM (4000) listen on
  127.0.0.1 only, for the script's health check and LiteLLM key setup.

Sign-in uses email and password (AC-4), with email links as a second way in. The confirmation, password reset and sign-in emails all go out through Brevo SMTP (`smtp-relay.brevo.com`, port 587). The domain is authenticated in Brevo with DKIM records in GoDaddy DNS. The SMTP key is in `/etc/stronghire/smtp.key` and in `.env`.

## First setup

1. In the domain's DNS, add three A records: `@`, `admin` and `rtc`, all to the server IP.
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

## Admin app

The admin app is at `https://admin.$DOMAIN`. Only admins (rows in `admin_users`, AA-1) can sign
in, with their own server-side session (cookie `sh_admin`, 2 h idle, 12 h at most). On the first
start, while that table is empty, the API fills it from `ADMIN_EMAILS`; after that the variable is
ignored. Manage admins in the admin app (Settings > Admins) or on the server:

```bash
docker exec strong-hire-api-1 strongctl admin list
docker exec strong-hire-api-1 strongctl admin add someone@example.com
docker exec strong-hire-api-1 strongctl admin remove someone@example.com   # also ends their sessions
```

Admins sign in with Google, an email link, or the password of their candidate account (the email
must be confirmed). `ADMIN_BASE_URL` (set by `infra/compose.server.yaml` to
`https://admin.$DOMAIN`) tells the API where email links and Google sign-in return.

To add the admin host to a running server:

1. Add the DNS A record `admin` to the server IP, and wait until `nslookup admin.<domain>`
   answers with it.
2. If Google sign-in is on (`GOOGLE_CLIENT_ID`), add this authorized redirect URI to the OAuth
   client in the Google Cloud console (APIs & Services > Credentials):
   `https://admin.<domain>/api/admin/auth/google/callback`. Until then, Google sign-in on the admin
   host fails with `redirect_uri_mismatch`; password and email links still work.
3. Deploy (`./scripts/server-deploy.sh`). Caddy gets the certificate for the new host on its
   first request.

## Marketing site

The marketing site (L04, `apps/site`, Astro) is built into the Caddy image as static files in
`/srv-site`. Until the domain switch it runs as a preview on `https://www.getstronghire.com`, with
`X-Robots-Tag: noindex`. Its waitlist form posts to `/api/public/waitlist` on the same host; Caddy
proxies only `/api/public/*` there.

Build settings (Docker build args of `infra/docker/caddy.Dockerfile`):

| Arg | Default | Meaning |
| --- | --- | --- |
| `SITE_URL` | `https://www.getstronghire.com` | Canonical origin for links and the sitemap |
| `PUBLIC_APP_URL` | `https://app.getstronghire.com` | Where "Sign in" and "Start free" go |
| `PUBLIC_CTA` | `waitlist` | `signup` switches the main button to "Start free" (Dec 14) |

Domain switch (Q9). Done on Oct 26: DNS `app`, the Google redirect URI
`https://app.getstronghire.com/api/auth/google/callback`, and `WEB_BASE_URL` / `API_PUBLIC_URL`
on `app.` (`infra/compose.server.yaml`). Left, when the pages are approved:

1. Caddyfile: remove `X-Robots-Tag` from the `www` block. The apex block stops serving the app: app
   paths (`/signin`, `/waitlist/*`, `/sessions/*`, `/jobs/*`, `/account` ...) redirect to `app.`,
   `/api/*` is still proxied for a few weeks (old email links), and everything else redirects to
   `www`.
2. Stripe webhook endpoint on `app.` (already), then remove the old Google redirect URI.
3. Deploy, then check that an old `/signin` link lands on `app.` and `/` lands on `www`.

## Update to the latest main

```bash
cd /opt/stronghire/strong-hire && ./scripts/server-deploy.sh
```

### Shell from the owner's PC

The Hetzner web console turns a typed `_` into `-`. For a normal root shell, the admin key
(`infra/server/admin-key.pub`, private half `~/.ssh/stronghire_admin` on the owner's PC) goes into
root's `authorized_keys`. Run once from the console:
`bash /opt/stronghire/strong-hire/infra/server/add-admin-key.sh`. Then, from PowerShell on the PC:
`ssh stronghire` (a `Host stronghire` entry in `~/.ssh/config`).

### Deploy from the owner's PC

The deploy key (`infra/server/deploy-key.pub`) can start a deploy and nothing else. Its private
half is `~/.ssh/stronghire_deploy` on the owner's PC. To add it on the server, run once:
`bash infra/server/add-deploy-key.sh`. It writes the key into root's `authorized_keys` with
`command="…/scripts/server-deploy.sh",restrict`, so the server ignores any other command.

To deploy: `ssh -i ~/.ssh/stronghire_deploy root@getstronghire.com`. Claude Code has an allow
rule for this exact command. To change the key, replace `deploy-key.pub` and run the script again.

## Test plans

Stripe is set up in test mode (Oct 26), so the old test-plan script and its cron job are removed.
To give someone paid access without paying, use a comp plan in the admin app (AU-5). Pay in
checkout with the Stripe test card `4242 4242 4242 4242`.

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
