"""Model of QuickDraw's 1-bit CopyBits stretching (StretchBits).

A bitmap here is a list of rows, each a list of 0/1 ints, with 1 meaning black.

QuickDraw scales a 1-bit image in two separable passes, both driven by an
error-term DDA:

* Vertically, it collects every source scanline that maps to the current
  destination row and ORs them into one buffer (the "merge" routine for
  1-bit sources). When enlarging, it reuses the buffer for several rows.
* Horizontally, StretchRow walks the merged row. When shrinking, the general
  loop sets the destination bit if *any* of the source bits feeding it is
  black. The fast paths for 3/4, 1/2, 1/4 and 1/8 are OR-based too. When
  enlarging, each source bit is simply replicated.

The result: shrinking is a box filter with OR as the combiner. A black pixel
can merge with its neighbours, but it never disappears, with one exception.
The vertical DDA is centred, so on a non-integral shrink the last few source
scanlines (fewer than half a destination row's worth) are never merged.
Integral shrinks (2:1, 3:1, ...) use a corrected error term and read every
row.
"""

ONE = 1 << 16


def _fix_ratio(numer, denom):
    """QuickDraw FixRatio: numer/denom as 16.16 fixed point."""
    return (numer << 16) // denom


def horizontal_map(src_w, dst_w):
    """For each destination column, the source columns that feed it.

    Mirrors SetupStretch / StretchRow: the 16-bit fraction is
    FixRatio(smaller, larger), and the error term starts at fraction/2.
    """
    if src_w <= 0 or dst_w <= 0:
        return []
    if src_w == dst_w:
        return [[i] for i in range(src_w)]
    if dst_w < src_w:
        # SHRINK: for every source bit, OR it into the current dst bit, then
        # advance the dst bit whenever the error term carries out of 16 bits.
        frac = _fix_ratio(dst_w, src_w) & 0xFFFF
        err = frac >> 1
        cols = [[] for _ in range(dst_w)]
        j = 0
        for i in range(src_w):
            if j < dst_w:
                cols[j].append(i)
            err += frac
            if err >= ONE:
                err -= ONE
                j += 1
        return cols
    # STRCH: for every dst bit, copy the current src bit, then advance the
    # src bit on carry.
    frac = _fix_ratio(src_w, dst_w) & 0xFFFF
    err = frac >> 1
    cols = []
    i = 0
    for _ in range(dst_w):
        cols.append([min(i, src_w - 1)])
        err += frac
        if err >= ONE:
            err -= ONE
            i += 1
    return cols


def vertical_map(src_h, dst_h):
    """For each destination row, the source rows ORed together to make it.

    Mirrors the VERROR loop in StretchBits: numer = dst height,
    denom = src height. The error starts at -(denom/2), or at -(denom-1)
    for an exact integral shrink.
    """
    if src_h <= 0 or dst_h <= 0:
        return []
    numer, denom = dst_h, src_h
    if denom > numer and denom % numer == 0:
        verror = -(denom - 1)
    else:
        verror = -(denom >> 1)

    rows = []
    src = 0
    while len(rows) < dst_h and src < src_h:
        # NEXTSRC / DoSrcMergeCase: take scanlines until VERROR > 0.
        group = []
        while src < src_h:
            group.append(src)
            src += 1
            verror += numer
            if verror > 0:
                break
        # Draw this merged row, repeating it while VERROR stays >= 0.
        while True:
            rows.append(group)
            if len(rows) == dst_h:
                break
            verror -= denom
            if verror < 0:
                break
    while len(rows) < dst_h:          # ran out of source: leave rows white
        rows.append([])
    return rows


def weighted_shrink_row(row, dst_w):
    """The disabled SHRINK loop (inside IF 0 in Stretch.a): ink accumulation.

    Every black source bit adds `ratio` (its width in destination pixels) to
    an ink accumulator that starts at ratio/2. After every source bit, black
    or white, if the ink exceeds 1.0 the current destination bit is set and
    1.0 is subtracted. If that bit is already set, the ink is kept "for next
    time" and spills into later bits. The accumulator is reset only at the
    start of each row, never between destination pixels.

    When the source runs out, the real loop keeps reading the scanline buffer
    until the destination is full. That is modelled as white bits, which
    still let leftover ink land.
    """
    src_w = len(row)
    if dst_w >= src_w:
        raise ValueError('the weighted loop is only used for shrinking')
    ratio = _fix_ratio(dst_w, src_w) & 0xFFFF
    err = ratio >> 1                  # position DDA, as in the shipping loop
    ink = ratio >> 1                  # "init bit accum to ratio/2"
    out = [0] * dst_w
    j = i = 0
    while j < dst_w:
        if i < src_w and row[i]:
            ink += ratio              # BLACK1: add weight of a set bit
        if ink > ONE and not out[j]:  # WHITE1: overflow into high word yet?
            out[j] = 1
            ink -= ONE                # (bit already set: save for next time)
        i += 1
        err += ratio
        if err >= ONE:                # FSCAN: time for next dst bit?
            err -= ONE
            j += 1
    return out


def stretch_bits(src, dst_w, dst_h, horizontal='or'):
    """Scale a 1-bit bitmap the way QuickDraw's CopyBits does (srcCopy).

    horizontal='weighted' swaps in the disabled ink-accumulating SHRINK loop
    for horizontal shrinks, which is what enabling the IF 0 block would do.
    The vertical pass still ORs scanlines either way.
    """
    if horizontal not in ('or', 'weighted'):
        raise ValueError(horizontal)
    src_h = len(src)
    src_w = len(src[0]) if src_h else 0
    weighted = horizontal == 'weighted' and dst_w < src_w
    cols = horizontal_map(src_w, dst_w)
    out = []
    for group in vertical_map(src_h, dst_h):
        merged = [0] * src_w
        for r in group:                       # OneDeep merge: OR scanlines
            row = src[r]
            for x in range(src_w):
                merged[x] |= row[x]
        if weighted:
            out.append(weighted_shrink_row(merged, dst_w))
        else:
            out.append([1 if any(merged[i] for i in c) else 0 for c in cols])
    return out


def nearest_neighbor(src, dst_w, dst_h):
    """Point-sampling baseline: each dst pixel copies one src pixel."""
    src_h = len(src)
    src_w = len(src[0]) if src_h else 0
    return [[src[(2 * y + 1) * src_h // (2 * dst_h)][(2 * x + 1) * src_w // (2 * dst_w)]
             for x in range(dst_w)] for y in range(dst_h)]
