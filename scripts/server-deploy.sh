#!/usr/bin/env bash
# Update the test server to the latest main and restart the stack (docs/hosting.md).
# Run on the server from the repo folder: ./scripts/server-deploy.sh
# It always deploys origin/main, whatever branch the checkout was on, stamps the web build with
# the commit (https://app.$DOMAIN/version.txt) and checks that the live site serves that commit.
set -euo pipefail
# Braces: bash reads the whole script before running it, so the checkout below can replace this file.
{
cd "$(dirname "$0")/.."

echo "==> Server checkout before: $(git rev-parse --abbrev-ref HEAD) $(git rev-parse --short HEAD)"
git fetch origin main
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "!! The server checkout has local changes; the deploy stops so they are not lost:" >&2
    git status --short >&2
    exit 1
fi
git checkout -B main origin/main
GIT_SHA="$(git rev-parse HEAD)"
export GIT_SHA
echo "==> Deploying $(git log -1 --format='%h %s')"

# The Anthropic key lives outside the repo, readable by root only. profile.ps1 passes it to LiteLLM.
ANTHROPIC_API_KEY="$(cat /etc/stronghire/anthropic.key)"
export ANTHROPIC_API_KEY
pwsh -NoProfile -File scripts/profile.ps1 claude -Voice

# The web build carries its commit; check that Caddy now serves it.
DOMAIN="$(sed -n 's/^DOMAIN=//p' .env | tr -d '"' | tail -1)"
LIVE=unreachable
for _ in 1 2 3 4 5 6; do
    LIVE="$(curl -fsS --max-time 20 -H 'Cache-Control: no-cache' "https://app.${DOMAIN}/version.txt" 2>/dev/null || echo unreachable)"
    [ "$LIVE" = "$GIT_SHA" ] && break
    sleep 5
done
if [ "$LIVE" = "$GIT_SHA" ]; then
    echo "==> Live: https://app.${DOMAIN} serves ${GIT_SHA:0:7}. Hard-refresh the browser (Ctrl+Shift+R)."
else
    echo "!! https://app.${DOMAIN}/version.txt says '${LIVE}', expected ${GIT_SHA}." >&2
    exit 1
fi
exit 0
}
