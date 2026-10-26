#!/usr/bin/env bash
# Test server only (docs/hosting.md): let the owner's admin key in infra/server/admin-key.pub sign
# in as root with a normal shell, so commands can be pasted from a terminal on the owner's PC
# instead of typed into the Hetzner web console (which turns "_" into "-").
# Run once from the console: bash /opt/stronghire/strong-hire/infra/server/add-admin-key.sh
# Safe to run more than once: it replaces the old line for the same key.
set -euo pipefail
cd "$(dirname "$0")/../.."

KEY="$(cat infra/server/admin-key.pub)"
BLOB="$(echo "$KEY" | awk '{print $2}')"
FILE=/root/.ssh/authorized_keys

install -d -m 700 /root/.ssh
touch "$FILE"
chmod 600 "$FILE"
grep -v -F "$BLOB" "$FILE" > "$FILE.new" || true
echo "$KEY" >> "$FILE.new"
mv "$FILE.new" "$FILE"
chmod 600 "$FILE"
echo "Admin key added. From the owner's PC: ssh stronghire"
