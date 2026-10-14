"""Reimplementation of how MacPaint 2.0 scales a 1-bit selection.

MacPaint 2.0 has no scaling code of its own: Scale Selection... and
stretch-dragging both hand the selection to QuickDraw's CopyBits with a
destination rectangle of a different size. This package models QuickDraw's 1-bit
stretch loops, whose shrink paths OR source pixels together, so black always
wins. See docs/macpaint2-scaling.md.
"""
from .qdstretch import (
    horizontal_map,
    nearest_neighbor,
    stretch_bits,
    vertical_map,
)
from .scalesel import ScaleTooBig, scale_selection_rect

__all__ = [
    'ScaleTooBig',
    'horizontal_map',
    'nearest_neighbor',
    'scale_selection_rect',
    'stretch_bits',
    'vertical_map',
]
