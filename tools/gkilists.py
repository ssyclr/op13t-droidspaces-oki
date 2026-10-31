#!/usr/bin/env python3
"""Pull the MODULE_SIG_PROTECT symbol tables out of a raw kernel Image.

Usage: gkilists.py <Image> <out dir>

kernel/module/gki_module.c embeds two sorted, fixed-width string arrays:
gki_unprotected_symbols (what unsigned modules may use, generated from
CONFIG_UNUSED_KSYMS_WHITELIST) and gki_protected_exports_symbols (what unsigned
modules may not export, from android/abi_gki_protected_exports_aarch64). If the
first is empty the kernel silently stops enforcing either rule, even with
CONFIG_MODULE_SIG_PROTECT=y.

Writes unprotected.txt and protected_exports.txt to <out dir>.

Standard library only.
"""
import os
import re
import sys

NAME = re.compile(rb'[A-Za-z_][A-Za-z0-9_.$]*')
# A symbol known to sit in each array. Exports of protected GKI modules are not
# in the unprotected array, so a probe can only match its own.
UNPROTECTED_PROBE = b'__traceiter_android_vh_cpufreq_acct_update_power'
PROTECTED_PROBES = (b'hci_cmd_sync', b'bt_sock_alloc', b'bt_err_ratelimited', b'baswap', b'alloc_canxl_skb')


def cell(data, off, width):
    """Return the NUL-padded name in a cell, or None if it is not one."""
    raw = data[off:off + width]
    name = raw.split(b'\0', 1)[0]
    if not name or raw[len(name):].strip(b'\0') or not NAME.fullmatch(name):
        return None
    return name


def walk(data, at, width):
    """Expand from one cell to the whole sorted array."""
    start = at
    while True:
        prev, here = cell(data, start - width, width), cell(data, start, width)
        if prev is None or prev >= here:
            break
        start -= width
    names = []
    p = start
    while True:
        name = cell(data, p, width)
        if name is None or (names and name <= names[-1]):
            break
        names.append(name)
        p += width
    return start, names


def find_array(data, probe, min_len):
    """Find the sorted fixed-width array that holds probe."""
    best = None
    pos = -1
    while True:
        pos = data.find(probe + b'\0', pos + 1)
        if pos < 0:
            break
        if pos and data[pos - 1]:
            continue
        for width in range(len(probe) + 1, 256):
            if cell(data, pos, width) is None:
                break
            prev = cell(data, pos - width, width)
            nxt = cell(data, pos + width, width)
            if prev is None or nxt is None or not prev < probe < nxt:
                continue
            start, names = walk(data, pos, width)
            if len(names) >= min_len and (best is None or len(names) > len(best[2])):
                best = (start, width, names)
    return best


def write(path, names):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.writelines(n.decode() + '\n' for n in names)


def main(image, out):
    with open(image, 'rb') as f:
        data = f.read()
    os.makedirs(out, exist_ok=True)
    found = find_array(data, UNPROTECTED_PROBE, 100)
    if found is None:
        print('gki_unprotected_symbols: not found (empty?)')
    else:
        start, width, names = found
        write(os.path.join(out, 'unprotected.txt'), names)
        print(f'gki_unprotected_symbols: {len(names)} names, width {width}, at {start:#x}')
    unprotected_at = found[0] if found else None
    for probe in PROTECTED_PROBES:
        found = find_array(data, probe, 10)
        if found and found[0] != unprotected_at:
            start, width, names = found
            write(os.path.join(out, 'protected_exports.txt'), names)
            print(f'gki_protected_exports_symbols: {len(names)} names, width {width}, at {start:#x}')
            return
    print('gki_protected_exports_symbols: not found')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
