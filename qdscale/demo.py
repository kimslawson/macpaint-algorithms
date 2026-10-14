"""Render QuickDraw OR-shrink vs. point sampling on a MacPaint-style test card.

    python3 -m qdscale.demo docs/images

Writes test-card.png and one comparison PNG per scale factor. Each comparison
shows QuickDraw (left) and nearest-neighbour (right), enlarged 3x so single
pixels are visible.
"""
import os
import struct
import sys
import zlib

from .qdstretch import nearest_neighbor, stretch_bits

ZOOM = 3
GAP = 12


def test_card(w=144, h=96):
    bm = [[0] * w for _ in range(h)]

    def put(x, y):
        if 0 <= x < w and 0 <= y < h:
            bm[y][x] = 1

    for x in range(w):                       # 1-px frame
        put(x, 0); put(x, h - 1)
    for y in range(h):
        put(0, y); put(w - 1, y)
    for i in range(8):                       # hairlines, spaced 4..16 px apart
        for y in range(6, 42):
            put(8 + i * (i + 3), y)
        for x in range(84, 136):
            put(x, 6 + i * 5)
    for t in range(80):                      # 1-px diagonals
        put(8 + t, 48 + t * 40 // 80)
        put(8 + t, 88 - t * 40 // 80)
    for y in range(48, 90):                  # 50% gray (checkerboard) swatch
        for x in range(96, 136):
            if (x + y) % 2 == 0:
                put(x, y)
    for x in range(100, 132):                # outlined white box with a dot inside
        for y in range(56, 82):
            bm[y][x] = 0
    for x in range(104, 128):
        put(x, 60); put(x, 77)
    for y in range(60, 78):
        put(104, y); put(127, y)
    put(115, 68)
    return bm


def write_png(path, rows):
    """Write a 1-bit grayscale PNG. rows: lists of 0/1 with 1 = black."""
    h, w = len(rows), len(rows[0])
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for x in range(0, w, 8):
            byte = 0
            for b in range(8):
                white = 1 if x + b >= w else 1 - row[x + b]
                byte |= white << (7 - b)
            raw.append(byte)

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c))

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 1, 0, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


def zoom(bm, k=ZOOM):
    return [[p for p in row for _ in range(k)] for row in bm for _ in range(k)]


def side_by_side(a, b, gap=GAP):
    return [ra + [0] * gap + rb for ra, rb in zip(a, b)]


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(outdir, exist_ok=True)
    card = test_card()
    write_png(os.path.join(outdir, 'test-card.png'), zoom(card))
    h, w = len(card), len(card[0])
    for pct in (75, 50, 37, 25):
        dw, dh = w * pct // 100, h * pct // 100
        qd = stretch_bits(card, dw, dh)
        nn = nearest_neighbor(card, dw, dh)
        name = f'shrink-{pct}.png'
        write_png(os.path.join(outdir, name), side_by_side(zoom(qd), zoom(nn)))
        print(f'{name}: {dw}x{dh}  black pixels: QuickDraw {sum(map(sum, qd))}, '
              f'nearest-neighbour {sum(map(sum, nn))}')


if __name__ == '__main__':
    main()
