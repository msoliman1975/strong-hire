#!/usr/bin/env bash
# Update the test server to the latest main and restart the stack (docs/hosting.md).
# Run on the server from the repo folder: ./scripts/server-deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
# The Anthropic key lives outside the repo, readable by root only. profile.ps1 passes it to LiteLLM.
ANTHROPIC_API_KEY="$(cat /etc/stronghire/anthropic.key)"
export ANTHROPIC_API_KEY
pwsh -NoProfile -File scripts/profile.ps1 claude -Voice
