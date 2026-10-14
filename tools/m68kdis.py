#!/usr/bin/env python3
"""Disassemble the CODE resources of a classic 68000 Mac application.

Input is a directory of resources as written by extract_rsrc.py (CODE_0.bin is
the jump table, CODE_n.bin are segments). For each segment it writes
OUTDIR/CODE_n.s, plus OUTDIR/symbols.txt. The listing:

  * names procedures from their embedded MacsBug symbols (the 8-character name
    that MPW Pascal places after each routine's RTS / JMP (A0), followed by a
    word giving the size of the routine's literal pool),
  * resolves inter-segment calls through the A5 jump table (JSR d(A5)),
  * names A-line toolbox/OS traps.

Requires capstone (pip install capstone).

    python3 tools/m68kdis.py res/ dis/
"""
import os
import re
import struct
import sys

from capstone import CS_ARCH_M68K, CS_MODE_BIG_ENDIAN, CS_MODE_M68K_000, Cs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from traps import T  # noqa: E402

SEGMENT_HEADER = 4            # first jump-table offset + entry count
JUMP_TABLE_A5_BASE = 32       # jump table starts at 32(A5)
RETURNS = (b'\x4e\x75', b'\x4e\xd0', b'\x4e\xd1')   # RTS, JMP (A0), JMP (A1)
MAX_LITERALS = 2048           # sanity bound on a routine's literal pool


def find_symbols(code):
    """Map offset -> name for MacsBug symbols that follow a return."""
    out = {}
    for i in range(SEGMENT_HEADER + 2, len(code) - 10):
        if code[i] < 0xC1 or code[i - 2:i] not in RETURNS:
            continue
        raw = bytes([code[i] & 0x7F]) + code[i + 1:i + 8]
        if re.fullmatch(rb'[A-Za-z_%][A-Za-z0-9_% ]{7}', raw):
            out[i] = raw.decode().strip()
    return out


def literal_pool_size(code, sym_off):
    n, = struct.unpack('>H', code[sym_off + 8:sym_off + 10])
    return n if n <= MAX_LITERALS else 0


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    resdir, outdir = sys.argv[1:]
    os.makedirs(outdir, exist_ok=True)

    segs = {}
    for f in os.listdir(resdir):
        m = re.fullmatch(r'CODE_(\d+)\.bin', f)
        if m and m.group(1) != '0':
            with open(os.path.join(resdir, f), 'rb') as fh:
                segs[int(m.group(1))] = fh.read()

    # Procedure start -> name. A routine starts right after the previous
    # routine's symbol and literal pool.
    symbols = {n: find_symbols(c) for n, c in segs.items()}
    procs = {}
    for n, syms in symbols.items():
        start = SEGMENT_HEADER
        for pos in sorted(syms):
            procs[(n, start)] = syms[pos]
            lit = literal_pool_size(segs[n], pos)
            start = pos + 10 + lit + (lit & 1)

    # Jump table: each 8-byte entry is  offset, MOVE.W #seg,-(SP), _LoadSeg.
    with open(os.path.join(resdir, 'CODE_0.bin'), 'rb') as fh:
        jt = fh.read()[16:]
    jump = {}
    for k in range(len(jt) // 8):
        off, move, seg, trap = struct.unpack('>HHHH', jt[8 * k:8 * k + 8])
        if move == 0x3F3C and trap == 0xA9F0:
            target = off + SEGMENT_HEADER
            name = procs.get((seg, target), f'seg{seg}_{target:04x}')
            jump[JUMP_TABLE_A5_BASE + 8 * k + 2] = (seg, target, name)

    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000 | CS_MODE_BIG_ENDIAN)
    for n, code in sorted(segs.items()):
        syms = symbols[n]
        starts = {o: name for (s, o), name in procs.items() if s == n}
        lines = [f'; CODE {n}  len={len(code)}']
        pc = SEGMENT_HEADER
        while pc < len(code):
            if pc in starts:
                lines.append(f'\n;================ {starts[pc]} ================')
            if pc in syms:
                lit = literal_pool_size(code, pc)
                pool = code[pc + 10:pc + 10 + lit].hex()
                lines.append(f'{pc:05x}  ; symbol "{syms[pc]}"  literals={lit}: {pool}')
                pc += 10 + lit + (lit & 1)
                continue
            w, = struct.unpack('>H', code[pc:pc + 2])
            if w & 0xF000 == 0xA000:
                name = T.get(f'{w:04X}') or T.get(f'{w & 0xF9FF:04X}', 'trap?')
                lines.append(f'{pc:05x}  {w:04x}             _{name}')
                pc += 2
                continue
            ins = next(md.disasm(code[pc:pc + 10], pc, 1), None)
            if ins is None:
                lines.append(f'{pc:05x}  {w:04x}             dc.w ${w:04x}')
                pc += 2
                continue
            text = f'{ins.mnemonic} {ins.op_str}'
            m = re.search(r'\$([0-9a-f]+)\(a5\)', ins.op_str)
            if m and ins.mnemonic in ('jsr', 'jmp', 'pea.l', 'lea.l'):
                hit = jump.get(int(m.group(1), 16))
                if hit:
                    text += f'    ; -> {hit[2]} [{hit[0]}:{hit[1]:04x}]'
            elif ins.mnemonic in ('jsr', 'bsr.w', 'bsr.b') or ins.mnemonic.startswith('bsr'):
                m = re.search(r'\$([0-9a-f]+)', ins.op_str)
                if m and int(m.group(1), 16) in starts:
                    text += f'    ; -> {starts[int(m.group(1), 16)]}'
            lines.append(f'{pc:05x}  {ins.bytes.hex():16s} {text}')
            pc += ins.size
        with open(os.path.join(outdir, f'CODE_{n}.s'), 'w') as fh:
            fh.write('\n'.join(lines) + '\n')

    with open(os.path.join(outdir, 'symbols.txt'), 'w') as fh:
        for (s, o), name in sorted(procs.items()):
            fh.write(f'{s:3d}:{o:05x} {name}\n')
        fh.write('\n; jump table\n')
        for a5, (s, o, name) in sorted(jump.items()):
            fh.write(f'{a5:5x}(A5) -> {s}:{o:05x} {name}\n')


if __name__ == '__main__':
    main()
