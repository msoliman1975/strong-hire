#!/usr/bin/env bash
# Keep /srv/stronghire/sim under SIM_KEEP_GB (default 10). Deletes the oldest run folders first
# and never the newest one. Run folder names start with a UTC timestamp, so name order is age order.
set -euo pipefail

DIR="${SIM_DIR:-/srv/stronghire/sim}"
KEEP_GB="${SIM_KEEP_GB:-10}"
limit=$((KEEP_GB * 1024 * 1024))   # KiB

mapfile -t runs < <(find "$DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
while [ "${#runs[@]}" -gt 1 ]; do
  used=$(du -sk "$DIR" | cut -f1)
  [ "$used" -le "$limit" ] && break
  oldest="${runs[0]}"
  echo "$(date -u +%FT%TZ) using ${used} KiB > ${limit} KiB; deleting $oldest"
  rm -rf -- "${DIR:?}/$oldest"
  runs=("${runs[@]:1}")
done
