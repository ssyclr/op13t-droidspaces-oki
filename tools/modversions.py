#!/usr/bin/env python3
"""Collect the symbol CRCs that kernel modules were built against.

Usage: modversions.py <out.tsv> <dir> [<dir> ...]

Each .ko records, in its __versions section, the CRC of every symbol it
imports: on arm64 one entry is 64 bytes, an 8 byte little-endian CRC followed
by a 56 byte NUL-terminated name. Writes "symbol, crc, module, provider" lines
to <out.tsv> (tab separated, sorted) and reports any symbol recorded with
different CRCs by different modules. provider names the module that exports
the symbol, or is "-" when no module does, which leaves vmlinux.

Standard library only.
"""
import os
import struct
import sys

SHT_NOBITS = 8
ENTRY = struct.Struct('<Q56s')
SYMBOL = struct.Struct('<IBBHQQ')  # Elf64_Sym
KSYMTAB = b'__ksymtab_'


def elf_sections(data):
    """Yield (name, type, offset, size) for each section of a 64-bit LE ELF."""
    if data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
        raise ValueError('not a 64-bit little-endian ELF file')
    shoff = struct.unpack_from('<Q', data, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x3a)
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize) for i in range(shnum)]
    strtab = headers[shstrndx][4]
    for h in headers:
        name_start = strtab + h[0]
        name = data[name_start:data.index(b'\0', name_start)].decode()
        yield name, h[1], h[4], h[5]


def read_versions(data):
    """Return [(crc, symbol)] from the __versions section of a module."""
    for name, kind, offset, size in elf_sections(data):
        if name == '__versions' and kind != SHT_NOBITS:
            if size % ENTRY.size:
                raise ValueError(f'__versions size {size} is not a multiple of {ENTRY.size}')
            return [(crc & 0xffffffff, raw.split(b'\0', 1)[0].decode())
                    for crc, raw in ENTRY.iter_unpack(data[offset:offset + size])]
    return []


def read_exports(data):
    """Return the symbols a module exports, from its __ksymtab_* symbols."""
    sections = {name: (offset, size) for name, _, offset, size in elf_sections(data)}
    if '.symtab' not in sections:
        return set()
    sym_off, sym_size = sections['.symtab']
    str_off = sections['.strtab'][0]
    exports = set()
    for i in range(0, sym_size, SYMBOL.size):
        name_off = SYMBOL.unpack_from(data, sym_off + i)[0]
        start = str_off + name_off
        if data[start:start + len(KSYMTAB)] == KSYMTAB:
            exports.add(data[start + len(KSYMTAB):data.index(b'\0', start)].decode())
    return exports


def main(out, dirs):
    rows = set()
    providers = {}
    modules = without_versions = 0
    for top in dirs:
        for root, _, files in os.walk(top):
            for name in files:
                if not name.endswith('.ko'):
                    continue
                with open(os.path.join(root, name), 'rb') as f:
                    data = f.read()
                entries = read_versions(data)
                modules += 1
                without_versions += not entries
                rows.update((sym, f'{crc:#010x}', name) for crc, sym in entries)
                for sym in read_exports(data):
                    providers.setdefault(sym, name)

    by_symbol = {}
    for sym, crc, mod in rows:
        by_symbol.setdefault(sym, {}).setdefault(crc, set()).add(mod)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        for row in sorted(rows):
            f.write('\t'.join(row + (providers.get(row[0], '-'),)) + '\n')

    print(f'modules: {modules} ({without_versions} without __versions)')
    print(f'lines: {len(rows)}, distinct symbols: {len(by_symbol)}')
    print(f'symbols exported by a module: {len(by_symbol.keys() & providers.keys())}, '
          f'left for vmlinux: {len(by_symbol.keys() - providers.keys())}')
    conflicts = {s: crcs for s, crcs in by_symbol.items() if len(crcs) > 1}
    print(f'symbols with conflicting CRCs: {len(conflicts)}')
    for sym, crcs in sorted(conflicts.items()):
        for crc, mods in sorted(crcs.items()):
            print(f'  {sym} {crc}: {" ".join(sorted(mods))}')
    return 1 if conflicts else 0


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2:]))
