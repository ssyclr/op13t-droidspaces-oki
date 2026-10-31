#!/usr/bin/env python3
"""Rebuild vmlinux.symvers from a raw arm64 kernel Image.

Usage: ksymtab.py <Image> <out.symvers>

There is no build output to download for an OEM kernel, but the Image carries
the export tables itself. The linker script places them back to back:

  __ksymtab  __ksymtab_gpl  __kcrctab  __kcrctab_gpl  __ksymtab_strings

Each export is 12 bytes of place-relative offsets (value, name, namespace),
sorted by name within each table, and the two CRC tables follow in the same
order. The output uses the vmlinux.symvers format, so kabi.load_symvers reads
it. Check the result against the CRCs modules recorded before relying on it.

Standard library only.
"""
import re
import struct
import sys

ENTRY = 12
ANCHOR = b'\0_printk\0'
IDENT = re.compile(rb'[A-Za-z_][A-Za-z0-9_.$]*\0')


def string_at(data, off):
    end = data.index(b'\0', off)
    return data[off:end]


def entry_name(data, off):
    """Return the name of the export entry at off, or None if it is not one."""
    if off < 0 or off + ENTRY > len(data):
        return None
    value, name, namespace = struct.unpack_from('<iii', data, off)
    target = off + 4 + name
    ns_target = off + 8 + namespace
    # lld tail-merges this string section, so a name may start mid-string.
    if not value or not 0 < target < len(data) or not 0 < ns_target < len(data):
        return None
    if data[ns_target] and not IDENT.match(data, ns_target, ns_target + 512):
        return None
    m = IDENT.match(data, target, target + 512)
    return m.group(0)[:-1] if m else None


def find_entry(data, target):
    """Find the export entry whose name field points at target."""
    for i, (value,) in enumerate(struct.iter_unpack('<i', data[:len(data) & ~3])):
        if value == target - 4 * i and entry_name(data, 4 * i - 4) is not None:
            return 4 * i - 4
    return None


def locate_table(data):
    """Return (start, count) of the combined __ksymtab + __ksymtab_gpl table."""
    pos = -1
    while True:
        pos = data.find(ANCHOR, pos + 1)
        if pos < 0:
            raise ValueError('cannot find the export table')
        off = find_entry(data, pos + 1)
        if off is not None:
            break
    start = off
    while entry_name(data, start - ENTRY) is not None:
        start -= ENTRY
    end = off + ENTRY
    while entry_name(data, end) is not None:
        end += ENTRY
    return start, (end - start) // ENTRY


def main(image, out):
    with open(image, 'rb') as f:
        data = f.read()
    start, count = locate_table(data)
    names = [entry_name(data, start + i * ENTRY) for i in range(count)]
    drops = [i for i in range(1, count) if names[i] < names[i - 1]]
    if len(drops) != 1:
        sys.exit(f'expected one sort break between __ksymtab and __ksymtab_gpl, found {len(drops)}')
    gpl_start = drops[0]
    crcs = struct.unpack_from(f'<{count}I', data, start + count * ENTRY)
    lines = []
    for i, name in enumerate(names):
        off = start + i * ENTRY
        namespace = struct.unpack_from('<i', data, off + 8)[0]
        ns = string_at(data, off + 8 + namespace).decode() if namespace else ''
        kind = 'EXPORT_SYMBOL_GPL' if i >= gpl_start else 'EXPORT_SYMBOL'
        lines.append(f'{crcs[i]:#010x}\t{name.decode()}\tvmlinux\t{kind}\t{ns}\n')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.writelines(sorted(lines, key=lambda line: line.split('\t')[1]))
    print(f'{out}: {count} exports ({gpl_start} EXPORT_SYMBOL, {count - gpl_start} GPL), table at {start:#x}')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
