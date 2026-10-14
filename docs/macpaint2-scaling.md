# How MacPaint 2.0 scales selections without losing black pixels

**Short answer:** MacPaint 2.0 has no scaling algorithm of its own. Both ways of
resizing a selection end in a single `_CopyBits` call: Goodies ▸ *Scale
Selection…* and stretch-dragging the selection. That call has a source
rectangle and a destination rectangle of a different size. The behaviour that
keeps black pixels comes from QuickDraw's 1-bit stretch loops in the Mac ROM.
When those loops shrink an image, they **OR** together all the source pixels
that land on a destination pixel, both horizontally and vertically. If any of
them is black, the result is black. A 1-pixel line therefore can't fall
"between" sample points the way it does with point sampling.

Binary analysed: *Mac Paint 2.0* (type `APPL`, creator `MPNT`), resource fork
149,251 bytes, created 1987-12-17, modified 1989-10-05. Its about box says
"Program by David Ramsey. Based on MacPaint by Bill Atkinson. Version 2.0,
December, 1987. Copyright © 1985-1987 CLARIS Corporation". The data fork holds
only the registration strings (`"Paul Brown"`, `"MIT"`).

---

## 1. Getting at the code

The upload `macpaint2.0.sea copy.hqx` is not actually BinHex. It is a raw
StuffIt 1.5 archive (`SIT!` signature). Its resource fork is compressed with
method 13 (LZ+Huffman).

```
unar -k visible mp2.sit                        # -> "Mac Paint 2.0.rsrc" (AppleDouble)
python3 tools/extract_rsrc.py "Mac Paint 2.0.rsrc" res/
python3 tools/m68kdis.py res/ dis/             # needs: pip install capstone
```

The application is MPW Pascal. Every routine ends with an old-style MacsBug
symbol: an 8-character name with the high bit set on the first byte, followed
by a word giving the size of the routine's literal pool. As a result, all 200+
procedures have names. The 26 `CODE` segments are named too:

| Seg | Name | Relevant routines |
|----:|------|-------------------|
| 1 | Main | `RECTTOSC`, `MASKTOAL`, `TRUNC` helper at `$7066` |
| 11 | UTILS | `SELTOALT` (draw the floating selection), `ACCEPTED`, `KILLSTUF` |
| 12 | SELECT | `DRAGIMAG` (move / stretch-drag a selection) |
| 18 | TOOLS | **`SCALESEL`** (Goodies ▸ Scale Selection…) |

The menu resources include `Goodies ▸ Scale Selection...` (MENU 4). They also
include an alternate Edit menu (MENU 9) with *Free Rotate / Distort /
Perspective / Stretch*. DLOG/DITL 2008 is the "Scale selection to: [  ] %"
dialog. ALRT/DITL 2120 is "That's too big to fit in a Paint document. Choose a
smaller scaling factor."

## 2. `SCALESEL` (CODE 18, `$2EE`): only rectangle arithmetic

This routine only computes a new rectangle:

```asm
002f6  move.b  -$378(a5),d0 / beq     ; selection floating? if so, ACCEPTED(true)
00318  _GetNewDialog 2008             ; "Scale selection to: [50] %"
003aa  _ModalDialog                   ; until OK (1) or Cancel (5)
00410  _GetIText / jsr StringToNum    ; percent as LongInt
0041e  tst.l pct / bgt                ; <= 0  -> KILLSTUF, bail
0042e  cmp.l #100,pct / bne           ; == 100 -> nothing to do
00444  FP68K $280E / $1010 / $100E    ; r := single(pct) ...
00466  FP68K $0006  (÷ 100.0)         ; ... / 100.0, stored as single
00494  w := right-left                ; selection rect at -$350(A5)
004a8  FP68K FI2X, FMULS r, negate, FADDI w, FDIVX 2.0
004ee  jsr $362(a5)                   ; TRUNC  (CODE 1 $7066: sets SANE
                                      ;  rounding to toward-zero, FX2L, restores)
...                                   ; same for height
0055a  _InsetRect(rect, dh, dv)
00564  if height > 720 or width > 576 -> Alert 2120, abort
0059a  OffsetRect to slide back inside 0..575 x 0..719 (top, bottom, right, left)
0061e  -$350(A5) := new rect          ; the selection's on-screen rect
0066e  jsr SELTOALT(new rect)         ; draw it
```

In other words:

```
dh = trunc((w - w*r) / 2)        dv = trunc((h - h*r) / 2)
newRect = InsetRect(selRect, dh, dv)       # scales about the centre
```

`qdscale/scalesel.py` reproduces this, including the single-precision ratio,
the truncation and the slide-back order.

## 3. `DRAGIMAG` (CODE 12, `$584`): stretch-dragging uses the same path

When a selection is dragged in stretch mode, `DRAGIMAG` builds the "from" and
"to" rectangles from the anchor corner and the mouse point (`_Pt2Rect`). It maps
the selection rectangle through them (`_MapRect`), clips to the page, and calls
the same `SELTOALT` with the result. Shift constrains it with `CONSTRAI`. This
runs on every mouse-move until `_StillDown` goes false.

## 4. `SELTOALT` (CODE 11, `$DB0`): the only pixel operation is `_CopyBits`

`SELTOALT(dstRect)` draws the floating selection into the offscreen document.
It uses a jump table on the current pen mode (`patCopy`…`notPatBic`) to pick a
transfer mode, sometimes inverting through a scratch bitmap first. Every case
reduces to one or two calls like this:

```asm
00e46  pea    -$1A04(a5)     ; srcBits  = selection bitmap (or its mask)
00e4a  pea    -$19E8(a5)     ; dstBits  = document bitmap
00e4e  pea    -$0360(a5)     ; srcRect  = ORIGINAL selection bounds
00e52  pea    -$8(a6)        ; dstRect  = new (scaled) rect
00e56  move.w #mode,-(a7)    ; srcCopy / srcOr / srcXor / srcBic
00e5a  clr.l  -(a7)          ; no maskRgn
00e5c  _CopyBits
```

Lasso selections go through `MASKTOAL` (CODE 1, `$16AC`), which is the same
`_CopyBits` with a mode argument. There is no other resampling code in the
program. The hand-written 68000 routines at the start of CODE 1 do row copies,
region scan-conversion and masked blits, but none of them scale.

**Design detail that matters:** `srcRect` is always `-$360(A5)`, the selection's
*original* bounds in the untouched selection buffer. Only `SETSELRE` writes it,
and that runs only when a selection is made or pasted (callers in SELECT, SCRAP
and TMENUSEG). `SCALESEL` and `DRAGIMAG` change only the destination rectangle
`-$350(A5)`. `ACCEPTED` (literal pool: "AcceptEdits") takes an Undo snapshot
and does not re-capture the selection. So while the selection is still
floating, every rescale and every drag frame resamples from the original
pixels. Detail merged away by a shrink comes back when you enlarge again.

## 5. QuickDraw: where black pixels are kept

`_CopyBits` with mismatched rectangles goes to `StretchBits`. These quotes are
from QuickDraw's `Stretch.a` (the later System 7-era ROM sources; see the
caveat below). The 1-bit paths do this:

### Horizontal: `SetupStretch` / `StretchRow`

`SetupStretch` computes `fract = FixRatio(dst, src)` and selects a loop.
`HALF`, `QRTR`, `EIGHTH` and `THREE4` handle 1/2, 1/4, 1/8 and 3/4. All other
ratios use the general `SHRINK`:

```asm
SHRINK  CLR     D1              ;INIT DST WORD
        MOVE    #$8000,D0       ;INIT SRC WORD
        MOVE    D0,D2           ;INIT MASK
        MOVE    D4,D3           ;COPY RATIO
        LSR     #1,D3           ;INIT ERR TO RATIO/2
NXTSRC1 ADD     D0,D0           ;GET SRC BIT
        BCC.S   WHITE1          ;BRANCH IF WHITE
        ...
BLACK1  OR      D2,D1           ;SET A BIT IN DST        <-- black wins
WHITE1  ADD     D4,D3           ;TIME FOR NEXT DSTBIT ?
        BCC     NXTSRC1         ;NO, LOOP MORE SRC
        ROR     #1,D2           ;YES, ROTATE MASK
```

Each source bit is ORed into the *current* destination bit. The destination bit
moves on only when the error term carries out of 16 bits. A white source bit
never clears anything. The fast paths are OR-based too. `HALF` does
`x | (x >> 1)` and masks with `$55555555`. `THREE4` and `QRTR` add `$C0000000`
or `$F0000000` so that the carry is the OR of the top 2 or 4 bits.

The same file also contains a different `SHRINK` that is switched off with
`IF 0`. It weighs black pixels instead of ORing them. See
[§5a](#5a-the-road-not-taken-the-disabled-ink-weighting-shrink) for what it
would have done.

Enlarging (`STRCH`, `DOUBLE`, `TRIPLE`, …) replicates source bits.

### Vertical: the `VERROR` DDA and `ONEDEEP` merge

For each destination row, `DoSrcMergeCase` keeps taking source scanlines while
`VERROR += numer.v` stays ≤ 0. It hands them to the 1-bit merge routine:

```asm
ONEDEEP ...
@Align  bfextu  (a0){d5:0},d0   ;get an aligned long of source
        move.l  d0,(a1)+        ;first scanline: copy
        ...
@NXTLNG bfextu  (a0){d5:0},d0
        or.l    d0,(a1)+        ;every further scanline: OR in   <-- black wins
```

`StretchRow` then runs on the merged row. The output pixel is therefore the OR
of the whole source box it covers.

### One exception: the bottom edge on non-integral shrinks

The vertical error starts at `-(srcHeight/2)`. For exact integral shrinks it
starts at `-(srcHeight-1)` instead; change log `<16>` (3/6/90) says "fixed error
term for vertical shrinking so expanding and then shrinking by an integral
amount does not alter the image". Because the error term is centred, a
non-integral shrink never merges the last ⌈srcH / (2·dstH)⌉ or fewer source
scanlines. For example, 5 → 2 rows merges rows {0,1} and {2,3} and never reads
row 4. Horizontally, every source column is used. So the "black never
disappears" guarantee holds everywhere except a sliver at the bottom of the
selection when the vertical ratio isn't a whole number. The tests in
`tests/test_qdscale.py` cover this explicitly.

### The downside

OR is also why MacPaint's reductions look heavy. A 50% gray (checkerboard) fill
shrinks to solid black, and closely spaced lines merge into blocks. Point
sampling keeps the gray but drops hairlines. See `docs/images/`: each
`shrink-NN.png` has three panels, zoomed 3×:

* **left:** QuickDraw as shipped (OR shrink)
* **middle:** QuickDraw with the disabled ink-weighting loop from §5a
* **right:** nearest-neighbour point sampling

| Scale | OR (shipped) black px | Ink-weighted (disabled) | Nearest-neighbour |
|------:|----------------------:|------------------------:|------------------:|
| 75% | 1481 | 1264 | 1192 |
| 50% | 918 | 792 | 495 |
| 37% | 634 | 468 | 169 |
| 25% | 430 | 313 | 114 |

The source card has 1843 black pixels.

## 5a. The road not taken: the disabled ink-weighting `SHRINK`

Just before the `SHRINK` that is built, `Stretch.a` contains a second version,
wrapped in `IF 0 THEN … ELSE` so it is never assembled:

```asm
        IF 0 THEN
SHRINK  MOVEM.L D7/D6,-(SP)
        MOVEQ   #0,D1           ;INIT DST WORD
        MOVE    #$1F,D2         ;init bit counter
        ...
        MOVE.L  D4,D3           ;COPY RATIO
        LSR.L   #1,D3           ;INIT ERR TO RATIO/2
        MOVE.L  D3,D7           ;init bit accum to ratio/2
        MOVEQ   #1,D6           ;use D6 to test for overflow
        SWAP    D6              ;into high word            (D6 = 1.0)
NXTSRC1 ADD.L   D0,D0           ;GET SRC BIT
        BCC.S   WHITE1          ;BRANCH IF WHITE
        ...
BLACK1  ADD.L   D4,D7           ;add weight of a set bit
WHITE1  CMP.L   D6,D7           ;overflow into high word yet?
        BLE.S   FSCAN           ;=>no, continue scanning
        BSET    D2,D1           ;else set the bit
        BNE.S   FSCAN           ;=>if already set, save for next time
        SUB.L   D6,D7           ;subtract one for bit we set
FSCAN   ADD     D4,D3           ;TIME FOR NEXT DSTBIT ?
        ...
        ELSE
SHRINK  CLR     D1              ; <- the OR loop shown above
```

### What it computes

The position DDA (`D3`) is the same as in the shipping loop. The difference is
a second accumulator, `D7`, which tracks **ink**:

```
ink = ratio/2                          # ratio = dst/src, < 1.0
for each source bit:
    if black: ink += ratio             # a black pixel is `ratio` dst pixels wide
    if ink > 1.0 and current dst bit is clear:
        set it; ink -= 1.0
    # if the bit is already set, the ink is "saved for next time"
    advance to the next dst bit when the position DDA carries
```

This is a one-dimensional, density-preserving threshold, close to 1-D error
diffusion of black coverage. Three details change the results:

1. **The ink check runs after every source bit, white ones too.** `WHITE1` is
   the check, and `BLACK1` falls through into it.
2. **`ink` is never reset between destination pixels**, only at the start of
   each row. Leftover ink carries to the right until something uses it.
3. **When the target bit is already set, the excess is kept**, so it spills
   into later bits even if their sources are white.

### What that does to a picture

The model is `weighted_shrink_row` in `qdscale/qdstretch.py`. Use
`stretch_bits(..., horizontal='weighted')` for a whole bitmap.
`tests/test_qdscale.py::WeightedShrinkTests` pins down each behaviour below.

* **Gray stays gray in a single row.** `1010101010101010` → 8 px comes out as
  `01010101`. Each row's black count stays within one pixel of
  `black pixels × ratio` (measured: −0.99 to +0.48 over 20,000 random rows).
  This is the property the loop was written for.
* **Lone pixels are rationed, not kept.** A single black pixel adds `ratio` of
  ink, and `ratio` is always under 1. Only the first one in a row gets the
  `ratio/2` head start, so a lone pixel in an otherwise white row needs a ratio
  above ⅔ to show at all. In general, n separate 1-px vertical lines come out
  as about n × ratio lines. In the test card's row of 9 verticals (8 hairlines
  plus the frame edge), 7 survive at 75%, 4 at 50% and 2 at 25%.
* **Ink drifts right.** At 50%, two lone pixels at x=4 and x=9 produce one dot
  at the *second* pixel's position, because the first one's 0.75 ink waits
  until the second pushes it over 1.0. The card's left frame edge is the first
  ink in every row, so it disappears entirely at 50% and below. Its ink lands
  on whatever black comes next in the row.
* **Action at a distance.** In the card, the dot inside the outlined box is
  under 1.0 on its own, so its ink moves right. It tops up the box's right
  edge, which then leaves the frame's right edge 16 px further on short. The
  dot punches a hole in a line it never touches (row 34 of `shrink-50.png`,
  middle panel).
* **It only covers half the problem.** The routine replaces only the
  *horizontal* shrink. The vertical pass still ORs scanlines (`ONEDEEP`), so a
  50% checkerboard still goes solid black at 50%: two rows `0101…` and `1010…`
  OR to `1111…` before the weighted loop sees them. The result is
  anisotropic. Horizontal hairlines are kept by the vertical OR, while vertical
  hairlines are thinned out by the horizontal ink budget.

For a paint program, where a 1-pixel line is a deliberate mark, that's a bad
trade. The shipping OR loop is predictable and local: an output pixel depends
only on its own source box, and nothing the user drew can vanish (except the
vertical edge case above).

### Where it came from

Nothing dates the block. It has no change-log entry and no initials. It is
written for 32-bit registers: `MOVE.L (A0)+`, `ADDX.L`, a 32-bit destination
word with bit counter `#$1F`, and `ADD.L D4,D7` with 1.0 = `$10000` in `D6`.
The shipping loop is the 16-bit word loop (`MOVE (A0)+`, `ROR #1,D2`), in the
same style as the rest of the original 68000 stretch code. So the most likely
story is that someone during Color QuickDraw development tried a
coverage-preserving shrink for 1-bit images and switched it off, leaving the
original OR behaviour in place. That reading is an inference from the code,
not something the source states. Either way, it was never assembled into the
ROM this file builds, and MacPaint 2.0 never used it.

## 6. Reimplementation

`qdscale/qdstretch.py` models the two DDAs and the OR merges exactly as
described above. `stretch_bits(src, w, h)` gives QuickDraw's result.
`stretch_bits(..., horizontal='weighted')` swaps in the disabled loop from §5a.
`nearest_neighbor` is the baseline. `qdscale/scalesel.py` is the Scale
Selection rectangle maths.

```
python3 -m unittest discover -s tests -t .
python3 -m qdscale.demo docs/images
```

## Caveats

* The MacPaint 2.0 findings above come from disassembling this exact binary.
* The QuickDraw quotes come from the later Color QuickDraw ROM `Stretch.a`
  (copyright 1981–1993), not from the 1987 Mac Plus/SE ROM that MacPaint 2.0
  usually ran on. The general `SHRINK` loop and the 1-bit row merge are
  word-at-a-time 68000 code from the original design, and the OR behaviour is
  the same for any 1-bit source. However, the `VERROR` initialisation shown
  dates from the 1990 changes. On older ROMs the exact rows picked at
  non-integral ratios may differ by one. Running MacPaint 2.0 in an emulator
  with a Plus or SE ROM would settle that.
* `FixRatio` rounding is modelled as truncation. If a ROM rounds instead, edge
  columns at some ratios could shift by one pixel. The OR behaviour is the
  same either way.
