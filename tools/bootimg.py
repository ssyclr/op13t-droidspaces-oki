#!/usr/bin/env python3
"""Read Android boot images without unpacking tools.

  bootimg.py info <boot.img>                 header fields and the AVB footer
  bootimg.py compare <stock.img> <new.img> <Image>
                                             check a repacked boot image
  bootimg.py kernel <boot.img> <out>         the kernel exactly as stored
  bootimg.py vendor-ramdisks <vendor_boot.img> <out_dir>
                                             each vendor ramdisk, as stored
  bootimg.py cpio <ramdisk> <out_dir> [suffix]
                                             files of a newc cpio archive (plain
                                             or LZ4 legacy), optionally only
                                             those with suffix
"""
import os
import struct
import sys

BOOT_MAGIC = b'ANDROID!'
VENDOR_MAGIC = b'VNDRBOOT'
AVB_FOOTER_SIZE = 64


def align(n, page):
    return (n + page - 1) // page * page


def parse_boot(data):
    """Header v3/v4 only: page size is fixed at 4096 there."""
    if data[:8] != BOOT_MAGIC:
        raise ValueError('not an Android boot image')
    kernel_size, ramdisk_size, os_version, header_size = struct.unpack_from('<IIII', data, 8)
    version = struct.unpack_from('<I', data, 40)[0]
    if version not in (3, 4):
        raise ValueError(f'unsupported boot header version {version}')
    page = 4096
    hdr = {
        'header_version': version,
        'header_size': header_size,
        'kernel_size': kernel_size,
        'ramdisk_size': ramdisk_size,
        'os_version': os_version,
        'cmdline': data[44:44 + 1536].split(b'\0', 1)[0].decode('ascii', 'replace'),
        'signature_size': struct.unpack_from('<I', data, 1580)[0] if version == 4 else 0,
        'kernel_offset': page,
        'ramdisk_offset': page + align(kernel_size, page),
    }
    return hdr


def parse_avb_footer(data):
    """Return the AVB footer at the end of a partition image, or None."""
    footer = data[-AVB_FOOTER_SIZE:]
    if footer[:4] != b'AVBf':
        return None
    major, minor, original_size, vbmeta_offset, vbmeta_size = struct.unpack_from('>IIQQQ', footer, 4)
    return {
        'version': f'{major}.{minor}',
        'original_image_size': original_size,
        'vbmeta_offset': vbmeta_offset,
        'vbmeta_size': vbmeta_size,
    }


def kernel_format(blob):
    if blob[:2] == b'\x1f\x8b':
        return 'gzip'
    if blob[:4] == b'\x02\x21\x4c\x18':
        return 'lz4_legacy'
    if blob[:4] == b'\x04\x22\x4d\x18':
        return 'lz4'
    if blob[:4] == b'\x28\xb5\x2f\xfd':
        return 'zstd'
    if blob[56:60] == b'ARM\x64':
        return 'raw (arm64 Image)'
    return 'unknown'


def parse_vendor_boot(data):
    if data[:8] != VENDOR_MAGIC:
        raise ValueError('not an Android vendor boot image')
    version, page, _, _, ramdisk_size = struct.unpack_from('<IIIII', data, 8)
    header_size, dtb_size = struct.unpack_from('<II', data, 2096)
    hdr = {'header_version': version, 'page_size': page, 'header_size': header_size,
           'vendor_ramdisk_size': ramdisk_size, 'dtb_size': dtb_size,
           'cmdline': data[28:28 + 2048].split(b'\0', 1)[0].decode('ascii', 'replace'),
           'name': data[2080:2096].split(b'\0', 1)[0].decode('ascii', 'replace')}
    base = align(header_size, page)
    hdr['ramdisks'] = []
    if version < 4:
        hdr['ramdisks'].append({'name': '', 'type': 0, 'offset': base, 'size': ramdisk_size})
        return hdr
    table_size, entries, entry_size, bootconfig_size = struct.unpack_from('<IIII', data, 2112)
    hdr['bootconfig_size'] = bootconfig_size
    table = base + align(ramdisk_size, page) + align(dtb_size, page)
    for i in range(entries):
        off = table + i * entry_size
        size, offset, kind = struct.unpack_from('<III', data, off)
        name = data[off + 12:off + 44].split(b'\0', 1)[0].decode('ascii', 'replace')
        hdr['ramdisks'].append({'name': name, 'type': kind, 'offset': base + offset, 'size': size})
    return hdr


def lz4_legacy_decompress(data):
    """Decompress an LZ4 legacy frame (magic 0x184c2102), as used for ramdisks."""
    if data[:4] != b'\x02\x21\x4c\x18':
        raise ValueError('not an LZ4 legacy frame')
    out = bytearray()
    p = 4
    while p + 4 <= len(data):
        size = struct.unpack_from('<I', data, p)[0]
        if size == 0 or size == 0x184c2102:  # padding or a concatenated frame
            p += 4
            continue
        p += 4
        end = p + size
        while p < end:
            token = data[p]
            p += 1
            literals = token >> 4
            if literals == 15:
                while True:
                    b = data[p]
                    p += 1
                    literals += b
                    if b != 255:
                        break
            out += data[p:p + literals]
            p += literals
            if p >= end:
                break
            offset = data[p] | data[p + 1] << 8
            p += 2
            length = token & 15
            if length == 15:
                while True:
                    b = data[p]
                    p += 1
                    length += b
                    if b != 255:
                        break
            length += 4
            start = len(out) - offset
            if offset >= length:
                out += out[start:start + length]
            else:
                for i in range(length):
                    out.append(out[start + i])
    return bytes(out)


def iter_cpio(data):
    """Yield (name, mode, body) from a newc cpio archive."""
    p = 0
    while p + 110 <= len(data):
        if data[p:p + 6] not in (b'070701', b'070702'):
            raise ValueError(f'bad cpio magic at {p:#x}')
        field = lambda i: int(data[p + 6 + 8 * i:p + 14 + 8 * i], 16)  # noqa: E731
        mode, filesize, namesize = field(1), field(6), field(11)
        name = data[p + 110:p + 110 + namesize - 1].decode()
        body_off = (p + 110 + namesize + 3) & ~3
        if name == 'TRAILER!!!':
            return
        yield name, mode, data[body_off:body_off + filesize]
        p = (body_off + filesize + 3) & ~3


def compare(stock_path, new_path, image_path):
    """Check that a repacked boot image is the stock one with only the kernel
    replaced. magiskboot drops the unreferenced 16 KiB signature block after
    the kernel and moves vbmeta up, so the footer offsets change with it, but
    the signed vbmeta blob itself must not."""
    with open(stock_path, 'rb') as f:
        stock = f.read()
    with open(new_path, 'rb') as f:
        new = f.read()
    with open(image_path, 'rb') as f:
        image = f.read()
    old_hdr, new_hdr = parse_boot(stock), parse_boot(new)
    old_avb, new_avb = parse_avb_footer(stock), parse_avb_footer(new)
    kernel = new[new_hdr['kernel_offset']:new_hdr['kernel_offset'] + new_hdr['kernel_size']]
    new_vbmeta = new[new_avb['vbmeta_offset']:new_avb['vbmeta_offset'] + new_avb['vbmeta_size']]
    old_vbmeta = stock[old_avb['vbmeta_offset']:old_avb['vbmeta_offset'] + old_avb['vbmeta_size']]
    checks = [
        ('image size unchanged', len(new) == len(stock)),
        ('kernel identical to Image', kernel == image),
        ('kernel stored raw', kernel_format(kernel[:64]).startswith('raw')),
        ('ramdisk still empty', new_hdr['ramdisk_size'] == 0),
    ]
    checks += [(f'header {k} unchanged', new_hdr[k] == old_hdr[k])
               for k in ('header_version', 'header_size', 'os_version', 'cmdline', 'signature_size')]
    checks += [
        ('AVB footer present', new_avb is not None),
        ('vbmeta blob identical to stock', new_vbmeta == old_vbmeta),
        ('footer points at the end of the image data',
         new_avb['original_image_size'] == new_avb['vbmeta_offset'] == new_hdr['ramdisk_offset']),
    ]
    for label, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {label}")
    return all(ok for _, ok in checks)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'compare' and len(argv) == 5:
        sys.exit(0 if compare(argv[2], argv[3], argv[4]) else 1)
    if cmd == 'info' and len(argv) == 3:
        with open(argv[2], 'rb') as f:
            data = f.read()
        hdr = parse_vendor_boot(data) if data[:8] == VENDOR_MAGIC else parse_boot(data)
        for k, v in hdr.items():
            print(f'{k}: {v}')
        if data[:8] == BOOT_MAGIC:
            print('kernel_format:', kernel_format(data[hdr['kernel_offset']:hdr['kernel_offset'] + 64]))
        print('avb_footer:', parse_avb_footer(data))
    elif cmd == 'kernel' and len(argv) == 4:
        with open(argv[2], 'rb') as f:
            data = f.read()
        hdr = parse_boot(data)
        with open(argv[3], 'wb') as f:
            f.write(data[hdr['kernel_offset']:hdr['kernel_offset'] + hdr['kernel_size']])
        print(f"{argv[3]}: {hdr['kernel_size']} bytes")
    elif cmd == 'vendor-ramdisks' and len(argv) == 4:
        with open(argv[2], 'rb') as f:
            data = f.read()
        hdr = parse_vendor_boot(data)
        os.makedirs(argv[3], exist_ok=True)
        for i, rd in enumerate(hdr['ramdisks']):
            path = os.path.join(argv[3], f"ramdisk{i}_{rd['name'] or 'default'}.bin")
            with open(path, 'wb') as f:
                f.write(data[rd['offset']:rd['offset'] + rd['size']])
            print(f"{path}: type={rd['type']} size={rd['size']}")
    elif cmd == 'cpio' and len(argv) in (4, 5):
        suffix = argv[4] if len(argv) == 5 else ''
        with open(argv[2], 'rb') as f:
            data = f.read()
        if data[:4] == b'!L':
            data = lz4_legacy_decompress(data)
        count = 0
        for name, mode, body in iter_cpio(data):
            if (mode & 0o170000) != 0o100000 or not name.endswith(suffix):
                continue
            path = os.path.join(argv[3], *name.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(body)
            count += 1
        print(f'{argv[3]}: {count} files')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
