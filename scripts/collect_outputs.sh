#!/usr/bin/env bash
# Gather what the report job and the person flashing need from one build.
# Nothing from the phone goes in here: only files this build produced.
# Usage: collect_outputs.sh <work dir> <out dir>
set -euo pipefail

WORK=$(realpath "$1")
OUT=$2
HERE=$(cd "$(dirname "$0")/.." && pwd)
COMMON=$WORK/common
BUILD=$WORK/out
IMAGE=$BUILD/arch/arm64/boot/Image
mkdir -p "$OUT"

cp "$IMAGE" "$BUILD/vmlinux.symvers" "$BUILD/System.map" "$BUILD/abi_symbollist.raw" "$OUT/"
"$COMMON/scripts/extract-ikconfig" "$IMAGE" > "$OUT/config"
python3 "$HERE/tools/extract.py" btf "$BUILD/vmlinux" "$OUT/vmlinux.btf"
python3 "$HERE/tools/gkilists.py" "$IMAGE" "$OUT/gki_lists"
grep -a -o -m1 'Linux version [[:print:]]*' "$IMAGE" > "$OUT/linux_version.txt"
git -C "$COMMON" rev-parse HEAD > "$OUT/common_head.txt"
git -C "$COMMON" status --porcelain > "$OUT/source_status.txt"
git -C "$COMMON" diff > "$OUT/source.diff"

# Listed options that are not Kconfig symbols in this tree at all.
: > "$OUT/kconfig_missing.txt"
while read -r opt _; do
  case "$opt" in ''|'#'*) continue ;; esac
  if ! grep -rqsE --include='Kconfig*' "^[[:space:]]*(menu)?config[[:space:]]+${opt}[[:space:]]*$" "$COMMON"; then
    echo "$opt" >> "$OUT/kconfig_missing.txt"
  fi
done < "$HERE/config/droidspaces_options.txt"

ls -la "$OUT"
cat "$OUT/linux_version.txt"
