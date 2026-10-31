#!/usr/bin/env bash
# Build Image the way the stock kernel was configured, with plain make.
#
# kleaf's kernel_aarch64 target applies two things on top of gki_defconfig that
# make does not: it trims exports to the KMI symbol lists, and it uses the same
# list as the table of symbols unsigned modules may use. Without that list the
# table stays empty and the kernel silently stops enforcing
# CONFIG_MODULE_SIG_PROTECT (see kernel/module/gki_module.c), so both are
# reproduced here, as kleaf does, without touching gki_defconfig.
#
# Usage: build_kernel.sh <work dir> <log dir>
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(realpath "$1")
LOGS=$(realpath -m "$2")
source "$HERE/config/device.env"
COMMON=$WORK/common
OUT=$WORK/out
mkdir -p "$OUT" "$LOGS"

export PATH="$WORK/clang/bin:$WORK/build-tools/bin:$PATH"
export ARCH=arm64 LLVM=1 LLVM_IAS=1 TZ=UTC
export KBUILD_BUILD_TIMESTAMP=$STOCK_BUILD_TIMESTAMP
export KBUILD_BUILD_VERSION=$STOCK_BUILD_VERSION
export KBUILD_BUILD_USER=$STOCK_BUILD_USER
export KBUILD_BUILD_HOST=$STOCK_BUILD_HOST
# Set but empty, so scripts/setlocalversion does not append "+".
export LOCALVERSION=

make_kernel() {
  make -j"$(nproc)" -C "$COMMON" O="$OUT" LD=ld.lld HOSTLD=ld.lld \
    KCFLAGS=-D__ANDROID_COMMON_KERNEL__ "$@"
}

make_kernel gki_defconfig

# The same inputs as aarch64_additional_kmi_symbol_lists in BUILD.bazel.
lists=$(sed -n '/name = "aarch64_additional_kmi_symbol_lists"/,/^)/p' "$COMMON/BUILD.bazel" \
  | sed -n 's/^ *"\(android\/abi_gki_aarch64_[a-z0-9_]*\)",$/\1/p')
if [ -z "$lists" ]; then
  echo "cannot find the KMI symbol lists in BUILD.bazel" >&2
  exit 1
fi
# awk, not cat: not every list ends in a newline.
(cd "$COMMON" && awk 1 android/abi_gki_aarch64 $lists) \
  | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^#/d' -e '/^$/d' -e '/^\[abi_symbol_list\]$/d' \
  | LC_ALL=C sort -u > "$OUT/abi_symbollist.raw"
echo "KMI symbol list: $(wc -l < "$OUT/abi_symbollist.raw") symbols from $(wc -w <<< "$lists") + 1 lists"

"$COMMON/scripts/config" --file "$OUT/.config" \
  --set-str LOCALVERSION "$STOCK_LOCALVERSION" \
  --disable LOCALVERSION_AUTO \
  --enable TRIM_UNUSED_KSYMS \
  --set-str UNUSED_KSYMS_WHITELIST abi_symbollist.raw
for opt in ${DISABLE_OPTIONS:-}; do
  echo "disable CONFIG_$opt"
  "$COMMON/scripts/config" --file "$OUT/.config" --disable "$opt"
done
make_kernel olddefconfig

make_kernel Image 2>&1 | tee "$LOGS/build.log"
df -h "$WORK"
