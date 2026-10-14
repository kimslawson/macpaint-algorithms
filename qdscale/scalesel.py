"""MacPaint 2.0's Goodies > Scale Selection... rectangle arithmetic.

Transcribed from SCALESEL (CODE 18 "TOOLS", offset $2EE). The routine only
computes a new destination rectangle. The pixels are then scaled by CopyBits,
modelled in qdstretch.py.
"""
import math
import struct

DOC_WIDTH = 576    # pixels, 8 inches at 72 dpi
DOC_HEIGHT = 720   # pixels, 10 inches


class ScaleTooBig(ValueError):
    """Alert 2120: "That's too big to fit in a Paint document. Choose a
    smaller scaling factor." """


def _single(x):
    """Round to IEEE single precision (SANE FX2S), as the Pascal 'real' did."""
    return struct.unpack('>f', struct.pack('>f', x))[0]


def scale_selection_rect(rect, percent):
    """Return the rectangle SCALESEL computes for `percent`.

    rect is (top, left, bottom, right) in document coordinates. It returns
    None for 100% (nothing to do). It raises ValueError for percent <= 0 and
    ScaleTooBig if the result is taller than 720 or wider than 576 pixels.
    """
    if percent <= 0:
        raise ValueError('scale factor must be positive')
    if percent == 100:
        return None
    top, left, bottom, right = rect
    ratio = _single(_single(percent) / 100.0)

    def inset(extent):
        # Extended-precision expression, then Pascal TRUNC (helper at
        # CODE 1 $7066 forces SANE rounding toward zero):
        #   trunc((extent - extent * ratio) / 2)
        return math.trunc((extent - extent * ratio) / 2.0)

    dh = inset(right - left)
    dv = inset(bottom - top)
    top, left, bottom, right = top + dv, left + dh, bottom - dv, right - dh  # InsetRect

    if bottom - top > DOC_HEIGHT or right - left > DOC_WIDTH:
        raise ScaleTooBig(percent)

    # Slide (not clip) the rectangle back onto the page, in SCALESEL's order.
    if top < 0:
        top, bottom = 0, bottom - top
    if bottom > DOC_HEIGHT - 1:
        top, bottom = top + (DOC_HEIGHT - 1 - bottom), DOC_HEIGHT - 1
    if right > DOC_WIDTH - 1:
        left, right = left + (DOC_WIDTH - 1 - right), DOC_WIDTH - 1
    if left < 0:
        left, right = 0, right - left
    return top, left, bottom, right
