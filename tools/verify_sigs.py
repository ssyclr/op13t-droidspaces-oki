#!/usr/bin/env python3
"""Verify the signature appended to every .ko in some directories.

Usage: verify_sigs.py <cert.pem> <out.tsv> <label=dir> [<label=dir> ...]

The signatures carry no certificate, so <cert.pem> is handed to
`openssl cms -verify` with -certfile. Writes one line per module to <out.tsv>
(label, module, signed?, verified?) and prints a pass/total count per label.
"""
import os
import struct
import subprocess
import sys
import tempfile

MAGIC = b'~Module signature appended~\n'
SIG_INFO = '>BBBBB3xI'  # struct module_signature
PKEY_ID_PKCS7 = 2


def split_signature(data):
    """Return (signed content, PKCS#7 blob), or None if the file has no signature."""
    if not data.endswith(MAGIC):
        return None
    info_end = len(data) - len(MAGIC)
    info_off = info_end - struct.calcsize(SIG_INFO)
    _, _, id_type, _, _, sig_len = struct.unpack_from(SIG_INFO, data, info_off)
    if id_type != PKEY_ID_PKCS7:
        raise ValueError(f'unexpected signature id type {id_type}')
    return data[:info_off - sig_len], data[info_off - sig_len:info_off]


def verify(cert, content, sig, workdir):
    content_path = os.path.join(workdir, 'content')
    sig_path = os.path.join(workdir, 'sig')
    with open(content_path, 'wb') as f:
        f.write(content)
    with open(sig_path, 'wb') as f:
        f.write(sig)
    run = subprocess.run(
        ['openssl', 'cms', '-verify', '-binary', '-inform', 'DER', '-in', sig_path,
         '-content', content_path, '-certfile', cert, '-nointern', '-noverify',
         '-out', os.devnull],
        capture_output=True, text=True, check=False)
    return run.returncode == 0, run.stderr.strip()


def main(cert, out, specs):
    rows = []
    with tempfile.TemporaryDirectory() as workdir:
        for spec in specs:
            label, path = spec.split('=', 1)
            passed = failed = unsigned = 0
            for root, _, files in os.walk(path):
                for name in sorted(files):
                    if not name.endswith('.ko'):
                        continue
                    with open(os.path.join(root, name), 'rb') as f:
                        parts = split_signature(f.read())
                    if parts is None:
                        unsigned += 1
                        rows.append((label, name, 'unsigned', ''))
                        continue
                    ok, err = verify(cert, parts[0], parts[1], workdir)
                    passed += ok
                    failed += not ok
                    rows.append((label, name, 'pass' if ok else 'fail', '' if ok else err.splitlines()[0]))
            total = passed + failed + unsigned
            print(f'{label}: {passed}/{total} pass, {failed} fail, {unsigned} unsigned')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write('\t'.join(row) + '\n')


if __name__ == '__main__':
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
