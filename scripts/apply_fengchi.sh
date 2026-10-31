#!/usr/bin/env bash
# Apply the unofficial Fengchi (HMBIRD) scheduler patch, pinned by commit and
# hash. OnePlus has not released this scheduler and the patch is built from
# leaked code, so it is downloaded at build time and never stored here.
#
# It lands as a local commit, so the gki_defconfig guard in apply_droidspaces.sh
# still sees only the Droidspaces changes.
# Usage: apply_fengchi.sh <common dir>
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
COMMON=$1
source "$HERE/config/device.env"

PATCH=$(mktemp)
curl -fsSL --retry 5 --retry-delay 15 -o "$PATCH" "$FENGCHI_PATCH_URL"
echo "$FENGCHI_PATCH_SHA256  $PATCH" | sha256sum -c -

cd "$COMMON"
patch -p1 --forward --fuzz=0 --dry-run < "$PATCH"
patch -p1 --forward --fuzz=0 --no-backup-if-mismatch < "$PATCH"
git add -A
git commit -q -m "Fengchi (HMBIRD) scheduler"
git show --stat --format=%s HEAD | tail -1
