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

# The patch was made against a tree without the dmabuf accounting in
# kernel/fork.c. Fix the context of those two hunks; every added and removed
# line stays as published.
python3 - "$PATCH" <<'EOF'
import sys

CONTEXT = (
    ('\tWARN_ON(tsk == current);\n', '\tio_uring_free(tsk);\n \tcgroup_free(tsk);\n \ttask_numa_free(tsk, true);\n',
     '\ttrace_android_vh_put_task(tsk);\n \tput_dmabuf_info(tsk->dmabuf_info);\n \tio_uring_free(tsk);\n'),
    ('-bad_fork_cancel_cgroup:\n', '\tcgroup_cancel_fork(p, args);\n bad_fork_put_pidfd:\n \tif (clone_flags & CLONE_PIDFD) {\n',
     '\tcgroup_cancel_fork(p, args);\n bad_fork_cleanup_dmabuf:\n \tput_dmabuf_info(p->dmabuf_info);\n'),
)

path = sys.argv[1]
with open(path, encoding='utf-8', errors='surrogateescape', newline='') as f:
    text = f.read()
start = text.index('diff --git b/kernel/fork.c')
end = text.index('diff --git ', start + 1)
fork = text[start:end]
for anchor, old, new in CONTEXT:
    at = fork.index(anchor)
    at = fork.index(old, at)
    fork = fork[:at] + new + fork[at + len(old):]
with open(path, 'w', encoding='utf-8', errors='surrogateescape', newline='') as f:
    f.write(text[:start] + fork + text[end:])
EOF

cd "$COMMON"
patch -p1 --forward --fuzz=0 --dry-run < "$PATCH"
patch -p1 --forward --fuzz=0 --no-backup-if-mismatch < "$PATCH"
git add -A
git commit -q -m "Fengchi (HMBIRD) scheduler"
git show --stat --format=%s HEAD | tail -1
