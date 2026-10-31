#!/usr/bin/env bash
# Fetch the pinned kernel source and the prebuilt toolchain, verifying both.
# Usage: sync_source.sh <work dir>
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=$1
source "$HERE/config/device.env"
mkdir -p "$WORK/common" "$WORK/clang"

git config --global user.name "github-actions"
git config --global user.email "github-actions@users.noreply.github.com"
git config --global color.ui false

cd "$WORK/common"
git init -q .
git remote add origin "$SOURCE_REPO"
git fetch --depth=1 origin "$SOURCE_SHA"
git checkout --detach -q FETCH_HEAD

ACTUAL=$(git rev-parse HEAD)
if [ "$ACTUAL" != "$SOURCE_SHA" ]; then
  echo "source pin mismatch: expected $SOURCE_SHA, got $ACTUAL" >&2
  exit 1
fi
VERSION=$(awk '/^VERSION = /{v=$3} /^PATCHLEVEL = /{p=$3} /^SUBLEVEL = /{s=$3; print v "." p "." s; exit}' Makefile)
if [ "$VERSION" != "$EXPECTED_KERNEL_VERSION" ]; then
  echo "Makefile says $VERSION, expected $EXPECTED_KERNEL_VERSION" >&2
  exit 1
fi
echo "source: $ACTUAL ($VERSION, $SOURCE_BRANCH_NOTE)"

fetch_zip() {
  curl -fsSL --retry 5 --retry-delay 15 -o "$WORK/tool.zip" "$1"
  echo "$2  $WORK/tool.zip" | sha256sum -c -
  unzip -q "$WORK/tool.zip" -d "$3"
  rm "$WORK/tool.zip"
}
fetch_zip "$CLANG_URL" "$CLANG_SHA256" "$WORK/clang"
fetch_zip "$BUILD_TOOLS_URL" "$BUILD_TOOLS_SHA256" "$WORK"
"$WORK/clang/bin/clang" --version | head -1
df -h "$WORK"
