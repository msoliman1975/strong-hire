#!/usr/bin/env bash
# Test server only (docs/hosting.md): let the deploy key in infra/server/deploy-key.pub start a
# deploy and nothing else. The key goes into root's authorized_keys with a forced command, so any
# command sent with it is ignored and scripts/server-deploy.sh runs instead. "restrict" turns off
# port forwarding, agent forwarding, X11 and the terminal.
# Safe to run more than once: it replaces the old line for the same key.
set -euo pipefail
cd "$(dirname "$0")/../.."

KEY="$(cat infra/server/deploy-key.pub)"
BLOB="$(echo "$KEY" | awk '{print $2}')"
DEPLOY="$(pwd)/scripts/server-deploy.sh"
FILE=/root/.ssh/authorized_keys

install -d -m 700 /root/.ssh
touch "$FILE"
chmod 600 "$FILE"
grep -v -F "$BLOB" "$FILE" > "$FILE.new" || true
echo "command=\"$DEPLOY\",restrict $KEY" >> "$FILE.new"
mv "$FILE.new" "$FILE"
chmod 600 "$FILE"
echo "Deploy key added. It can only run $DEPLOY."
