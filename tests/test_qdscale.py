import math
import random
import unittest

from qdscale import (ScaleTooBig, horizontal_map, nearest_neighbor,
                     scale_selection_rect, stretch_bits, vertical_map,
                     weighted_shrink_row)


def blank(w, h):
    return [[0] * w for _ in range(h)]


def black_count(bm):
    return sum(map(sum, bm))


class MapTests(unittest.TestCase):
    def test_horizontal_shrink_uses_every_source_column_once(self):
        for src in range(2, 120):
            for dst in range(1, src):
                m = horizontal_map(src, dst)
                self.assertEqual(len(m), dst)
                self.assertTrue(all(m), (src, dst))
                self.assertEqual([i for g in m for i in g], list(range(src)))

    def test_vertical_shrink_skips_tail_rows_unless_ratio_is_integral(self):
        # The VERROR DDA is centred, so on a non-integral shrink the last
        # source scanlines (under half a destination row's worth) are never
        # merged. Integral shrinks use the <16> error fix and lose nothing.
        for src in range(2, 120):
            for dst in range(1, src):
                m = vertical_map(src, dst)
                self.assertEqual(len(m), dst)
                self.assertTrue(all(m), (src, dst))
                flat = [i for g in m for i in g]
                self.assertEqual(flat, list(range(len(flat))))
                dropped = src - len(flat)
                if src % dst == 0:
                    self.assertEqual(dropped, 0, (src, dst))
                self.assertLessEqual(dropped, math.ceil(src / (2 * dst)))
        self.assertEqual(vertical_map(5, 2), [[0, 1], [2, 3]])

    def test_maps_replicate_when_enlarging(self):
        for src in range(1, 30):
            for dst in range(src, 3 * src + 1):
                for m in (horizontal_map(src, dst), vertical_map(src, dst)):
                    self.assertEqual(len(m), dst)
                    self.assertTrue(all(len(g) == 1 for g in m))
                    self.assertEqual(sorted({g[0] for g in m}), list(range(src)))

    def test_integral_ratios_are_aligned_boxes(self):
        for k in (2, 3, 4, 8):
            self.assertEqual(horizontal_map(8 * k, 8),
                             [list(range(k * j, k * j + k)) for j in range(8)])
            self.assertEqual(vertical_map(8 * k, 8),
                             [list(range(k * j, k * j + k)) for j in range(8)])


class StretchTests(unittest.TestCase):
    def test_black_pixel_never_lost_when_shrinking(self):
        rng = random.Random(1)
        for _ in range(300):
            sw, sh = rng.randint(2, 40), rng.randint(2, 40)
            dw, dh = rng.randint(1, sw), rng.randint(1, sh)
            used_rows = {r for g in vertical_map(sh, dh) for r in g}
            bm = blank(sw, sh)
            y = rng.choice(sorted(used_rows))
            bm[y][rng.randrange(sw)] = 1
            self.assertEqual(black_count(stretch_bits(bm, dw, dh)), 1)

    def test_one_pixel_lines_survive_where_point_sampling_drops_them(self):
        bm = blank(30, 30)
        for y in range(30):
            bm[y][6] = 1      # 1-px vertical line
        for x in range(30):
            bm[12][x] = 1     # 1-px horizontal line
        qd = stretch_bits(bm, 10, 10)
        self.assertTrue(all(any(r) for r in qd))             # vertical line intact
        self.assertTrue(any(all(r) for r in qd))             # horizontal line intact
        nn = nearest_neighbor(bm, 10, 10)
        self.assertEqual(black_count(nn), 0)                 # sampling misses both

    def test_enlarge_then_shrink_round_trips(self):
        rng = random.Random(2)
        for k in (2, 3, 4):
            bm = [[rng.randint(0, 1) for _ in range(9)] for _ in range(7)]
            big = stretch_bits(bm, 9 * k, 7 * k)
            self.assertEqual(stretch_bits(big, 9, 7), bm)

    def test_shrink_is_or_of_source_box(self):
        rng = random.Random(3)
        for _ in range(100):
            sw, sh = rng.randint(2, 25), rng.randint(2, 25)
            dw, dh = rng.randint(1, sw), rng.randint(1, sh)
            bm = [[int(rng.random() < 0.1) for _ in range(sw)] for _ in range(sh)]
            hm, vm = horizontal_map(sw, dw), vertical_map(sh, dh)
            want = [[int(any(bm[y][x] for y in vm[j] for x in hm[i]))
                     for i in range(dw)] for j in range(dh)]
            self.assertEqual(stretch_bits(bm, dw, dh), want)


def bits(s):
    return [int(c) for c in s]


class WeightedShrinkTests(unittest.TestCase):
    """The ink-accumulating SHRINK loop that Stretch.a leaves disabled."""

    def test_isolated_pixel_needs_ratio_above_two_thirds(self):
        # ink = ratio/2 + ratio must exceed 1.0
        for dst in range(1, 40):
            row = [0] * 40
            row[20] = 1
            self.assertEqual(sum(weighted_shrink_row(row, dst)),
                             int(dst / 40 > 2 / 3), dst)

    def test_ink_drifts_to_the_next_black_pixel(self):
        # 0.75 ink from the first pixel tops up the second: one dot, at the
        # second pixel's position.
        self.assertEqual(weighted_shrink_row(bits('000010000100'), 6),
                         bits('000010'))

    def test_one_dot_can_erase_a_distant_pixel(self):
        # box edge, then frame edge 16 px further on (as in the demo card, row 34)
        edges = bits('0' * 23 + '1' + '0' * 15 + '1')
        with_dot = list(edges)
        with_dot[11] = 1
        self.assertEqual(sum(weighted_shrink_row(edges, 20)), 1)
        out = weighted_shrink_row(with_dot, 20)
        self.assertEqual(out[19], 0)          # frame pixel gone
        self.assertEqual(sum(out), 1)

    def test_preserves_density_not_lines(self):
        self.assertEqual(weighted_shrink_row(bits('10' * 8), 8), bits('01' * 4))
        self.assertEqual(weighted_shrink_row(bits('1' * 8), 4), bits('1111'))
        self.assertEqual(weighted_shrink_row(bits('111000000000'), 6),
                         bits('100000'))

    def test_row_black_count_tracks_ink(self):
        rng = random.Random(4)
        for _ in range(2000):
            sw = rng.randint(2, 60)
            dw = rng.randint(1, sw - 1)
            p = rng.random()
            row = [int(rng.random() < p) for _ in range(sw)]
            diff = sum(weighted_shrink_row(row, dw)) - sum(row) * dw / sw
            self.assertTrue(-1 < diff <= 0.5, (row, dw, diff))

    def test_only_used_for_horizontal_shrinks(self):
        rng = random.Random(6)
        bm = [[rng.randint(0, 1) for _ in range(9)] for _ in range(7)]
        self.assertEqual(stretch_bits(bm, 20, 3, horizontal='weighted'),
                         stretch_bits(bm, 20, 3))
        with self.assertRaises(ValueError):
            weighted_shrink_row([1, 0], 2)


class ScaleSelectionTests(unittest.TestCase):
    def test_hundred_percent_is_a_no_op(self):
        self.assertIsNone(scale_selection_rect((10, 10, 50, 50), 100))

    def test_scales_about_the_centre(self):
        self.assertEqual(scale_selection_rect((100, 100, 200, 180), 50),
                         (125, 120, 175, 160))
        self.assertEqual(scale_selection_rect((100, 100, 200, 180), 200),
                         (50, 60, 250, 220))

    def test_inset_truncates_toward_zero(self):
        # width 33 at 50%: (33 - 16.5) / 2 = 8.25 -> 8, so the result is 17 wide
        self.assertEqual(scale_selection_rect((0, 0, 33, 33), 50), (8, 8, 25, 25))
        # growing: (33 - 49.5) / 2 = -8.25 -> -8
        self.assertEqual(scale_selection_rect((100, 100, 133, 133), 150),
                         (92, 92, 141, 141))

    def test_result_is_slid_back_onto_the_page(self):
        self.assertEqual(scale_selection_rect((0, 0, 100, 100), 200),
                         (0, 0, 200, 200))
        # 150 tall x 75 wide after insetting; bottom and right overhang
        self.assertEqual(scale_selection_rect((600, 520, 700, 570), 150),
                         (569, 501, 719, 575))

    def test_too_big_raises(self):
        with self.assertRaises(ScaleTooBig):
            scale_selection_rect((0, 0, 400, 400), 200)
        with self.assertRaises(ValueError):
            scale_selection_rect((0, 0, 10, 10), 0)


if __name__ == '__main__':
    unittest.main()
