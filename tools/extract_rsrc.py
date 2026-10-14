#!/usr/bin/env python3
"""Dump every resource in a classic Mac OS resource fork to its own file.

Accepts either a raw resource fork or an AppleDouble file (what `unar -k visible`
writes as "<name>.rsrc"). Each resource is written to OUTDIR as TYPE_ID.bin and
a listing is printed to stdout.

    python3 tools/extract_rsrc.py "Mac Paint 2.0.rsrc" res/
"""
import os
import struct
import sys

APPLEDOUBLE_MAGIC = 0x00051607
RESOURCE_FORK_ENTRY = 2


def resource_fork(data):
    """Return the raw resource fork, unwrapping AppleDouble if needed."""
    magic, = struct.unpack('>I', data[:4])
    if magic != APPLEDOUBLE_MAGIC:
        return data
    count, = struct.unpack('>H', data[24:26])
    for k in range(count):
        entry_id, offset, length = struct.unpack('>III', data[26 + 12 * k:38 + 12 * k])
        if entry_id == RESOURCE_FORK_ENTRY:
            return data[offset:offset + length]
    raise ValueError('AppleDouble file has no resource fork entry')


def resources(fork):
    """Yield (type, id, attrs, name, data) for each resource in the fork."""
    data_off, map_off, _, map_len = struct.unpack('>IIII', fork[:16])
    rmap = fork[map_off:map_off + map_len]
    type_list_off, name_list_off = struct.unpack('>HH', rmap[24:28])
    ntypes = struct.unpack('>H', rmap[type_list_off:type_list_off + 2])[0] + 1
    for t in range(ntypes):
        p = type_list_off + 2 + 8 * t
        rtype, count, ref_off = struct.unpack('>4sHH', rmap[p:p + 8])
        for r in range(count + 1):
            e = type_list_off + ref_off + 12 * r
            rid, name_off, attr_and_off = struct.unpack('>hHI', rmap[e:e + 8])
            attrs, off = attr_and_off >> 24, attr_and_off & 0xFFFFFF
            length, = struct.unpack('>I', fork[data_off + off:data_off + off + 4])
            body = fork[data_off + off + 4:data_off + off + 4 + length]
            name = ''
            if name_off != 0xFFFF:
                n = name_list_off + name_off
                name = rmap[n + 1:n + 1 + rmap[n]].decode('mac_roman')
            yield rtype.decode('mac_roman'), rid, attrs, name, body


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, outdir = sys.argv[1:]
    os.makedirs(outdir, exist_ok=True)
    with open(src, 'rb') as f:
        fork = resource_fork(f.read())
    for rtype, rid, attrs, name, body in resources(fork):
        safe = rtype.replace(' ', '_').replace('/', '_')
        with open(os.path.join(outdir, f'{safe}_{rid}.bin'), 'wb') as f:
            f.write(body)
        print(f'{rtype} {rid:6d} len={len(body):6d} attr={attrs:02x} {name}')


if __name__ == '__main__':
    main()
