#!/usr/bin/env bash
# Make the kernel trust the stock module-signing certificate so the stock
# system_dlkm modules, signed by the key of the stock build, keep verifying.
# This adds one certificate and changes no structure or exported symbol, so
# both variants carry it.
# Usage: trust_stock_cert.sh <common dir> <stock cert pem>
set -euo pipefail

COMMON=$1
cp "$2" "$COMMON/certs/stock_module_signing.pem"
echo 'CONFIG_SYSTEM_TRUSTED_KEYS="certs/stock_module_signing.pem"' >> "$COMMON/arch/arm64/configs/gki_defconfig"
