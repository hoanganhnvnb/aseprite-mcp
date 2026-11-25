"""Pixel shapes as runs per row, computed before anything runs in Aseprite."""

from collections.abc import Iterable, Mapping, Sequence
from itertools import groupby

Span = tuple[int, int]
# canvas row -> sorted, disjoint inclusive (x0, x1) spans
Rows = dict[int, list[Span]]

UNTOUCHED = (".", " ")


def merge(spans: Iterable[Span]) -> list[Span]:
    out: list[Span] = []
    for left, right in sorted(spans):
        if out and left <= out[-1][1] + 1:
            if right > out[-1][1]:
                out[-1] = (out[-1][0], right)
        else:
            out.append((left, right))
    return out


def subtract(spans: list[Span], cut: list[Span]) -> list[Span]:
    """Both lists merged; returns the parts of `spans` not covered by `cut`."""
    out = []
    for left, right in spans:
        for cl, cr in cut:
            if cr < left or cl > right:
                continue
            if cl > left:
                out.append((left, cl - 1))
            left = cr + 1
            if left > right:
                break
        if left <= right:
            out.append((left, right))
    return out


def union(*shapes: Rows) -> Rows:
    out: dict[int, list[Span]] = {}
    for shape in shapes:
        for y, spans in shape.items():
            out.setdefault(y, []).extend(spans)
    return {y: merge(spans) for y, spans in out.items()}


def outline(shape: Rows, blocked: Rows) -> Rows:
    """Pixels 4-adjacent to `shape` that are not in `blocked`."""
    out: Rows = {}
    ys = {y + dy for y in shape for dy in (-1, 0, 1)}
    for y in sorted(ys):
        near = [(left - 1, right + 1) for left, right in shape.get(y, [])]
        near += shape.get(y - 1, []) + shape.get(y + 1, [])
        spans = subtract(merge(near), blocked.get(y, []))
        if spans:
            out[y] = spans
    return out


def ascii_art(x: int, y: int, rows: Sequence[str], legend: Mapping[str, object]) -> dict[str, Rows]:
    """Runs per legend character for text art whose first character sits at (x, y).

    '.' and ' ' are skipped; any other character missing from the legend raises
    ValueError naming its 1-based row and column.
    """
    by_char: dict[str, Rows] = {}
    for i, row in enumerate(rows):
        j = 0
        for char, group in groupby(row):
            n = len(list(group))
            if char not in UNTOUCHED:
                if char not in legend:
                    raise ValueError(f"row {i + 1}, column {j + 1}: {char!r} is not in the legend")
                by_char.setdefault(char, {}).setdefault(y + i, []).append((x + j, x + j + n - 1))
            j += n
    return by_char


def isometric_box(x: int, y: int, w: int, d: int, h: int) -> tuple[Rows, Rows, Rows]:
    """Top, left and right faces of a 2:1 box; see draw_isometric_box for the geometry.

    A pixel belongs to a face when its centre is strictly inside it. Shared edges never
    pass through a pixel centre, so every pixel of the box lands in exactly one face.
    """
    top: Rows = {}
    left: Rows = {}
    right: Rows = {}
    for r in range(w + d + h):
        faces = (
            (top, max(-2 * r - 1, 2 * r - 4 * d + 1), min(4 * w - 2 * r - 2, 2 * r)),
            (left, max(-2 * d, 2 * r - 4 * d - 2 * h + 1), min(2 * w - 2 * d - 1, 2 * r - 4 * d)),
            (
                right,
                max(2 * w - 2 * d, 4 * w - 2 * r - 1),
                min(2 * w - 1, 4 * w + 2 * h - 2 * r - 2),
            ),
        )
        for face, lo, hi in faces:
            if lo <= hi:
                face[y + r] = [(x + lo, x + hi)]
    return top, left, right
