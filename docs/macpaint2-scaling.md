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

(In the same file there is a commented-out alternative, inside `IF 0`, that
weights black bits and only sets the destination once they pass a threshold.
The plain OR version is the one that is built.)

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
`shrink-NN.png` has QuickDraw's OR shrink on the left and nearest-neighbour on
the right, zoomed 3×.

| Scale | QuickDraw black px | Nearest-neighbour black px |
|------:|-------------------:|---------------------------:|
| 75% | 1481 | 1192 |
| 50% | 918 | 495 |
| 37% | 634 | 169 |
| 25% | 430 | 114 |

## 6. Reimplementation

`qdscale/qdstretch.py` models the two DDAs and the OR merges exactly as
described above. `stretch_bits(src, w, h)` gives QuickDraw's result.
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
