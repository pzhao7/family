"""Column segmentation for vertical, right-to-left text.

Auto mode finds column boundaries from the vertical ink-projection (gaps between
columns are low-ink valleys). Manual overrides: --cols N (even split) or
--bounds x0,x1,... (explicit fractional cut lines). Columns are always returned
right-to-left to match reading order.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import image


@dataclass
class Column:
    index: int          # 1 = rightmost (read first)
    x0: float
    x1: float
    y0: float = 0.0
    y1: float = 1.0


def detect(src, *, min_column_frac: float) -> list[Column]:
    """Auto-detect column bands from the ink projection, ordered right-to-left."""
    proj = image.column_projection(src)
    w = len(proj)
    thresh = proj.mean() * 0.35          # valleys below this are inter-column gaps
    inked = proj > thresh

    # collect contiguous inked runs => column bands
    bands: list[tuple[int, int]] = []
    start = None
    for x, on in enumerate(inked):
        if on and start is None:
            start = x
        elif not on and start is not None:
            bands.append((start, x))
            start = None
    if start is not None:
        bands.append((start, w))

    min_px = min_column_frac * w
    bands = [(a, b) for a, b in bands if (b - a) >= min_px]
    if not bands:
        return [Column(1, 0.0, 1.0)]

    # right-to-left, with a small symmetric pad into the neighbouring gap
    bands.sort(key=lambda b: b[0], reverse=True)
    cols: list[Column] = []
    for i, (a, b) in enumerate(bands):
        pad = (b - a) * 0.06
        cols.append(Column(i + 1, max(0.0, (a - pad) / w), min(1.0, (b + pad) / w)))
    return cols


def even(n: int) -> list[Column]:
    """N equal-width columns, right-to-left."""
    step = 1.0 / n
    return [Column(i + 1, 1.0 - (i + 1) * step, 1.0 - i * step) for i in range(n)]


def from_bounds(bounds: list[float]) -> list[Column]:
    """Explicit fractional cut lines (e.g. 0,0.2,0.45,1.0) -> columns, right-to-left."""
    edges = sorted(set(bounds))
    pairs = list(zip(edges[:-1], edges[1:]))
    pairs.reverse()                      # right-to-left
    return [Column(i + 1, a, b) for i, (a, b) in enumerate(pairs)]


def split_tall(col: Column, src, *, ratio: float) -> list[Column]:
    """If a column is much taller than wide, split top/bottom for closer reading.

    Returns sub-boxes that share the column index (re-joined after extraction).
    """
    w, h = image.size(src)
    cw = (col.x1 - col.x0) * w
    ch = (col.y1 - col.y0) * h
    if cw <= 0 or ch / cw < ratio:
        return [col]
    mid = (col.y0 + col.y1) / 2
    overlap = (col.y1 - col.y0) * 0.04   # small overlap so a char on the seam isn't lost
    return [
        Column(col.index, col.x0, col.x1, col.y0, mid + overlap),
        Column(col.index, col.x0, col.x1, mid - overlap, col.y1),
    ]
