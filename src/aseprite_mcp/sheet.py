"""Contact sheets of rendered frames for view_sprite, composed with Pillow."""

from dataclasses import dataclass
from math import isqrt

from PIL import Image, ImageDraw, ImageFont

MAX_SIDE = 2048
DEFAULT_SIDE = 512
MAX_SCALE = 32
GAP = 4
GRID_MIN_SCALE = 4
CHECKER = 8

BACKDROP = (48, 48, 48, 255)
CHECK_LIGHT = 230
CHECK_DARK = 200
GRID_COLOR = (0, 0, 0, 90)
RULER_COLOR = (220, 220, 220, 255)


@dataclass
class Layout:
    scale: int
    # >1 means the frames are shown at 1/shrink size; scale is then 1.
    shrink: int
    columns: int
    rows: int
    cell: tuple[int, int]
    margin: tuple[int, int]
    size: tuple[int, int]
    notes: list[str]


def _columns(count: int) -> int:
    root = isqrt(count)
    return root if root * root == count else root + 1


def plan(w: int, h: int, count: int, scale: int | None, margin: tuple[int, int] = (0, 0)) -> Layout:
    """Pick the zoom for `count` frames of w x h laid out in a near-square grid.

    Without a scale the largest one up to MAX_SCALE that keeps the sheet within
    DEFAULT_SIDE is used (at least 1). Anything over MAX_SIDE is scaled down, below
    1 by showing every n-th pixel.
    """
    columns = _columns(count)
    rows = -(-count // columns)
    left, top = margin

    def layout(s: int, k: int) -> Layout:
        cell = (-(-w // k) * s, -(-h // k) * s)
        size = (
            left + columns * cell[0] + (columns - 1) * GAP,
            top + rows * cell[1] + (rows - 1) * GAP,
        )
        return Layout(s, k, columns, rows, cell, margin, size, [])

    if scale is None:
        fitting = (s for s in range(MAX_SCALE, 0, -1) if max(layout(s, 1).size) <= DEFAULT_SIDE)
        scale = next(fitting, 1)
        asked = None
    else:
        asked = scale
    chosen = layout(scale, 1)
    if max(chosen.size) <= MAX_SIDE:
        return chosen

    for s in range(scale - 1, 0, -1):
        smaller = layout(s, 1)
        if max(smaller.size) <= MAX_SIDE:
            if asked is not None:
                wide, side = chosen.size[0], "wide"
                if chosen.size[1] > wide:
                    wide, side = chosen.size[1], "tall"
                smaller.notes.append(
                    f"requested scale {asked} would make the image {wide} px {side}; reduced to {s}"
                )
            return smaller

    k = 2
    while max(layout(1, k).size) > MAX_SIDE:
        k += 1
    shrunk = layout(1, k)
    if asked is not None:
        shrunk.notes.append(f"requested scale {asked} does not fit {MAX_SIDE} px; reduced")
    shrunk.notes.append(
        f"shown at 1/{k} size (one pixel out of {k} in each direction) to stay within "
        f"{MAX_SIDE} px; pass a region or fewer frames to see every pixel"
    )
    return shrunk


def onion(previous: list[Image.Image], current: Image.Image) -> Image.Image:
    """`current` over the frames before it, nearest first: 50%, 25%, 12.5%... opacity."""
    out = Image.new("RGBA", current.size, (0, 0, 0, 0))
    for k in range(len(previous), 0, -1):
        strength = 256 >> k
        faded = previous[k - 1].copy()
        faded.putalpha(faded.getchannel("A").point(lambda a, s=strength: (a * s + 127) // 255))
        out.alpha_composite(faded)
    out.alpha_composite(current)
    return out


def _checkerboard(w: int, h: int) -> Image.Image:
    columns, rows = -(-w // CHECKER), -(-h // CHECKER)
    even = bytes(i % 2 for i in range(columns))
    odd = bytes(1 - v for v in even)
    data = b"".join(odd if r % 2 else even for r in range(rows))
    lut = [CHECK_LIGHT, CHECK_DARK] + [0] * 254
    tiles = Image.frombytes("L", (columns, rows), data).point(lut)
    board = tiles.resize((columns * CHECKER, rows * CHECKER), Image.Resampling.NEAREST)
    return board.crop((0, 0, w, h)).convert("RGBA")


def _grid(cell: Image.Image, step: int) -> None:
    draw = ImageDraw.Draw(cell, "RGBA")
    w, h = cell.size
    for x in range(step, w, step):
        draw.line([(x, 0), (x, h - 1)], fill=GRID_COLOR)
    for y in range(step, h, step):
        draw.line([(0, y), (w - 1, y)], fill=GRID_COLOR)


def _font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default()


def _ruler_margin(origin: tuple[int, int], w: int, h: int) -> tuple[int, int]:
    font = _font()
    widest = max(str(origin[0] + w), str(origin[1] + h), str(origin[0]), str(origin[1]), key=len)
    _, top, _, bottom = font.getbbox("0123456789")
    return int(font.getlength(widest)) + 8, int(bottom - top) + 8


def _ruler_step(pixel: float, label: float) -> int:
    step = 1
    while step * pixel < label + 6:
        step *= 2
    return step


def _rulers(sheet: Image.Image, layout: Layout, origin: tuple[int, int], w: int, h: int) -> None:
    font = _font()
    draw = ImageDraw.Draw(sheet)
    left, top = layout.margin
    cw, ch = layout.cell
    pixel = layout.scale / layout.shrink
    label = font.getlength(str(max(origin[0] + w, origin[1] + h)))
    _, text_top, _, text_bottom = font.getbbox("0")
    step = _ruler_step(pixel, label)
    for column in range(layout.columns):
        x0 = left + column * (cw + GAP)
        for c in range(-(-origin[0] // step) * step, origin[0] + w + 1, step):
            x = x0 + round((c - origin[0]) * pixel)
            draw.line([(x, top - 4), (x, top - 1)], fill=RULER_COLOR)
            if x + font.getlength(str(c)) <= x0 + cw + GAP:
                draw.text((x + 1, 1 - text_top), str(c), fill=RULER_COLOR, font=font)
    step = _ruler_step(pixel, text_bottom - text_top)
    for row in range(layout.rows):
        y0 = top + row * (ch + GAP)
        for c in range(-(-origin[1] // step) * step, origin[1] + h + 1, step):
            y = y0 + round((c - origin[1]) * pixel)
            draw.line([(left - 4, y), (left - 1, y)], fill=RULER_COLOR)
            if y + text_bottom - text_top <= y0 + ch + GAP:
                width = font.getlength(str(c))
                draw.text((left - 6 - width, y - text_top), str(c), fill=RULER_COLOR, font=font)


def render(
    frames: list[Image.Image],
    origin: tuple[int, int],
    scale: int | None,
    grid: bool = False,
    rulers: bool = False,
) -> tuple[Image.Image, Layout]:
    """Lay the frames out left to right, then down, over a checkerboard.

    `origin` is the canvas position of the frames' top-left pixel, for the rulers.
    Returns the sheet and its layout; layout.notes says what was changed or left out.
    """
    w, h = frames[0].size
    margin = _ruler_margin(origin, w, h) if rulers else (0, 0)
    layout = plan(w, h, len(frames), scale, margin)
    show_grid = grid and layout.shrink == 1 and layout.scale >= GRID_MIN_SCALE
    if grid and not show_grid:
        layout.notes.append(f"grid needs scale {GRID_MIN_SCALE} or more; left out")
    sheet = Image.new("RGBA", layout.size, BACKDROP)
    board = _checkerboard(*layout.cell)
    left, top = margin
    cw, ch = layout.cell
    for i, frame in enumerate(frames):
        cell = board.copy()
        cell.alpha_composite(frame.resize(layout.cell, Image.Resampling.NEAREST))
        if show_grid:
            _grid(cell, layout.scale)
        column, row = i % layout.columns, i // layout.columns
        sheet.paste(cell, (left + column * (cw + GAP), top + row * (ch + GAP)))
    if rulers:
        _rulers(sheet, layout, origin, w, h)
    return sheet, layout
