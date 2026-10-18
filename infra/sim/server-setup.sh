#!/usr/bin/env bash
# One-time setup on the main server (stronghire-test) for AI candidate results (P13).
#   sudo bash infra/sim/server-setup.sh "<upload public key line>"
#
# - /srv/stronghire/sim holds one folder per run. It is never deleted with the sim server.
# - User "simup" can only write there: its key is forced to rrsync, with no shell, no forwarding.
# - Retention (SIM_KEEP_GB, SIM_KEEP_DAYS) is done by the sim service (SM-14); this script
#   removes the cron job older versions installed.
# Safe to run more than once.
set -euo pipefail

PUBKEY="${1:?usage: server-setup.sh '<ssh-ed25519 AAAA... comment>'}"
DIR=/srv/stronghire/sim
REPO=/opt/stronghire/strong-hire

id simup >/dev/null 2>&1 || useradd --system --create-home --shell /bin/sh simup
mkdir -p "$DIR" /home/simup/.ssh
chown simup:simup "$DIR"
chmod 750 "$DIR"
echo "command=\"/usr/bin/rrsync $DIR\",restrict $PUBKEY" > /home/simup/.ssh/authorized_keys
chown -R simup:simup /home/simup/.ssh
chmod 700 /home/simup/.ssh
chmod 600 /home/simup/.ssh/authorized_keys

rm -f /etc/cron.d/stronghire-sim-retention /usr/local/bin/stronghire-sim-retention
echo "simup and $DIR are ready. Retention runs in the sim service (--profile sim)."
