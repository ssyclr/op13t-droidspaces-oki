#!/usr/bin/env bash
# Put a new Image into the stock boot image, on the phone, without writing any
# partition. Runs on the PC over adb and pulls the result back.
#
# Usage: package_boot.sh <stock boot.img> <Image> <variant> <out dir>
#
# magiskboot must already be on the phone at $DIR/magiskboot. KernelSU-Next
# 3.4.2 does not ship it, so it comes from the official Magisk APK. It runs as
# the shell user: `adb shell` is root on this phone, so that has to be explicit.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
STOCK=$1
IMAGE=$2
VARIANT=$3
OUT=$4
DIR=/data/local/tmp/ds13t_mb
export MSYS_NO_PATHCONV=1

as_shell() { adb shell "su 2000 -c 'cd $DIR && $1'" | tr -d '\r'; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

mkdir -p "$OUT"
adb shell "chmod 777 $DIR"
adb push "$(cygpath -m "$STOCK")" "$DIR/boot_stock.img" >/dev/null
adb push "$(cygpath -m "$IMAGE")" "$DIR/Image.$VARIANT" >/dev/null

as_shell "rm -rf repack && mkdir repack && cd repack && ../magiskboot unpack ../boot_stock.img 2>&1"
if [ -n "$(as_shell "ls repack/kernel_dtb 2>/dev/null")" ]; then
  echo "kernel_dtb was split off: dropping it so stock data is not appended to the new Image"
fi
as_shell "cd repack && rm -f kernel kernel_dtb && cp ../Image.$VARIANT kernel && ../magiskboot repack ../boot_stock.img ../new-boot-$VARIANT.img 2>&1"

# Unpack the result again: the kernel must come back byte for byte.
as_shell "rm -rf check && mkdir check && cd check && ../magiskboot unpack ../new-boot-$VARIANT.img 2>&1" | grep -E 'KERNEL_SZ|KERNEL_FMT|RAMDISK_SZ|VBMETA'
unpacked=$(as_shell "cat check/kernel check/kernel_dtb 2>/dev/null | sha256sum" | cut -d' ' -f1)
if [ "$unpacked" != "$(sha "$IMAGE")" ]; then
  echo "unpacked kernel does not match $IMAGE" >&2
  exit 1
fi

adb pull "$DIR/new-boot-$VARIANT.img" "$(cygpath -m "$OUT")/new-boot-$VARIANT.img" >/dev/null
as_shell "rm -rf repack check boot_stock.img Image.$VARIANT new-boot-$VARIANT.img"
python -I "$(cygpath -m "$HERE/tools/bootimg.py")" compare "$(cygpath -m "$STOCK")" \
  "$(cygpath -m "$OUT")/new-boot-$VARIANT.img" "$(cygpath -m "$IMAGE")"
sha256sum "$OUT/new-boot-$VARIANT.img"
