from typing import Annotated, Any, Literal

from pydantic import Field

from .. import raster
from ..colors import RGBA, color_rgba, pack_rgba
from ..models import Color, Coord, Pixel, Point, Rect
from ._registry import op_tool

MAX_PIXELS = 16384
MAX_POINTS = 4096

DrawLayer = Annotated[
    str,
    Field(description="Layer name or 'group/child' path; empty = the bottom-most normal layer"),
]
DrawFrame = Annotated[int, Field(ge=1, description="1-based frame number")]
CreateCel = Annotated[
    bool, Field(description="Add an empty cel when the layer has none in that frame")
]
Blend = Annotated[
    bool,
    Field(
        description="false: pixels get exactly this colour (transparent erases, except on "
        "a background layer, which ignores alpha); "
        "true: the colour is alpha-blended over what is there. On indexed sprites the "
        "result snaps to the nearest palette entry, so a faint colour paints a solid one"
    ),
]
Thickness = Annotated[int, Field(ge=1, le=64, description="Brush size in pixels")]
Fill = Annotated[bool, Field(description="Fill the shape; false draws the outline only")]
Area = Annotated[Rect, Field(description="Canvas rectangle to paint")]
Left = Annotated[Coord, Field(description="Canvas x of the top-left pixel")]
Top = Annotated[Coord, Field(description="Canvas y of the top-left pixel")]


def rgba(color: str) -> list[int]:
    return list(color_rgba(color))


def target(layer: str, frame: int, create_cel: bool) -> dict[str, Any]:
    return {"layer": layer, "frame": frame, "create_cel": create_cel}


def points_list(points: list[Point]) -> list[list[int]]:
    return [[p.x, p.y] for p in points]


@op_tool("draw_pixels", mutates=True, batch_hint=True)
def draw_pixels(
    pixels: Annotated[
        list[Pixel],
        Field(min_length=1, max_length=MAX_PIXELS, description="Pixels as {x, y, color}"),
    ],
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
) -> dict[str, Any]:
    """Set individual pixels to exact colours (no blending; a later entry wins).

    Pixels outside the canvas are skipped and counted in skipped_outside. The cel grows
    to take in pixels outside it; content beyond the canvas is kept. Works on every
    colour mode: indexed sprites get the nearest palette entry, 'transparent' writes
    the transparent index. A background layer stays opaque: alpha is ignored there, so
    'transparent' paints opaque black (the nearest palette colour on indexed sprites).

    Example: {"path": "hero.aseprite", "pixels": [{"x": 2, "y": 3, "color": "#d95763"},
    {"x": 3, "y": 3, "color": "transparent"}]}
    """
    return {
        **target(layer, frame, create_cel),
        "pixels": " ".join(f"{p.x} {p.y} {pack_rgba(color_rgba(p.color))}" for p in pixels),
    }


@op_tool("draw_line", mutates=True, batch_hint=True)
def draw_line(
    points: Annotated[
        list[Point],
        Field(min_length=2, max_length=MAX_POINTS, description="Line vertices as {x, y}, in order"),
    ],
    color: Color,
    thickness: Thickness = 1,
    closed: Annotated[bool, Field(description="Also connect the last point to the first")] = False,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Draw a polyline through the points, clipped to the canvas.

    The brush is a thickness x thickness square on every line pixel. Odd sizes are
    centred; even sizes reach one pixel further right and down (thickness 2 covers the
    pixel and its right/lower neighbours), so a horizontal line is exactly `thickness`
    rows tall.
    """
    return {
        **target(layer, frame, create_cel),
        "points": points_list(points),
        "color": rgba(color),
        "thickness": thickness,
        "closed": closed,
        "blend": blend,
    }


@op_tool("draw_rect", mutates=True, batch_hint=True)
def draw_rect(
    rect: Annotated[Rect, Field(description="Rectangle in canvas pixels")],
    color: Color,
    fill: Fill = False,
    thickness: Annotated[
        int, Field(ge=1, le=64, description="Outline width inside the rect; ignored with fill")
    ] = 1,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Draw a rectangle outline (growing inwards with thickness) or a filled rectangle.

    Clipped to the canvas.

    Example: {"path": "hero.aseprite", "rect": {"x": 4, "y": 4, "w": 8, "h": 6},
    "color": "#3366ff", "fill": true}
    """
    return {
        **target(layer, frame, create_cel),
        "rect": rect.model_dump(),
        "color": rgba(color),
        "fill": fill,
        "thickness": thickness,
        "blend": blend,
    }


@op_tool("draw_ellipse", mutates=True, batch_hint=True)
def draw_ellipse(
    cx: Annotated[Coord, Field(description="Centre x")],
    cy: Annotated[Coord, Field(description="Centre y")],
    rx: Annotated[int, Field(ge=0, le=4096, description="Horizontal radius in pixels")],
    ry: Annotated[int, Field(ge=0, le=4096, description="Vertical radius in pixels")],
    color: Color,
    fill: Fill = False,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Draw an ellipse centred on (cx, cy), 2*rx+1 pixels wide and 2*ry+1 tall.

    rx == ry draws a circle; a zero radius gives a line, both zero a single pixel. The
    outline is exactly the border of the filled shape. Clipped to the canvas.
    """
    return {
        **target(layer, frame, create_cel),
        "cx": cx,
        "cy": cy,
        "rx": rx,
        "ry": ry,
        "color": rgba(color),
        "fill": fill,
        "blend": blend,
    }


@op_tool("draw_polygon", mutates=True, batch_hint=True)
def draw_polygon(
    points: Annotated[
        list[Point],
        Field(min_length=3, max_length=MAX_POINTS, description="Corners as {x, y}, in order"),
    ],
    color: Color,
    fill: Fill = True,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Draw a closed polygon through the points: filled (with its outline) or outline only.

    Filling uses the even-odd rule, so self-intersecting shapes leave the overlapping
    parts empty. Clipped to the canvas.
    """
    return {
        **target(layer, frame, create_cel),
        "points": points_list(points),
        "color": rgba(color),
        "fill": fill,
        "blend": blend,
    }


@op_tool("fill_area", mutates=True, batch_hint=True)
def fill_area(
    x: Annotated[Coord, Field(description="Seed pixel x")],
    y: Annotated[Coord, Field(description="Seed pixel y")],
    color: Color,
    contiguous: Annotated[
        bool, Field(description="false: replace every matching pixel of the layer's canvas")
    ] = True,
    tolerance: Annotated[
        int, Field(ge=0, le=255, description="Largest per-channel RGBA difference that matches")
    ] = 0,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
) -> dict[str, Any]:
    """Flood-fill the area around (x, y) whose colour matches the seed pixel's.

    Neighbours are the 4 pixels left, right, above and below. Only the layer itself is
    looked at (not the composited image); outside its cel the layer counts as
    transparent, so filling an empty area covers it up to the canvas edges. The seed
    must be on the canvas. Pixels get exactly the colour, without blending.
    """
    return {
        **target(layer, frame, create_cel),
        "x": x,
        "y": y,
        "color": rgba(color),
        "contiguous": contiguous,
        "tolerance": tolerance,
    }


MATRIX_SIZE = {"bayer2": 2, "bayer4": 4, "bayer8": 8}
Matrix = Annotated[
    Literal["bayer2", "bayer4", "bayer8"], Field(description="Bayer matrix size of the pattern")
]


@op_tool("draw_gradient", mutates=True, batch_hint=True)
def draw_gradient(
    rect: Area,
    colors: Annotated[
        list[Color], Field(min_length=2, max_length=16, description="Gradient stops, evenly spaced")
    ],
    direction: Annotated[
        Literal["horizontal", "vertical"], Field(description="horizontal runs left to right")
    ] = "horizontal",
    dither: Annotated[
        Literal["none", "bayer2", "bayer4", "bayer8"],
        Field(description="Ordered dithering between stops; none gives hard bands"),
    ] = "none",
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Fill rect with a linear gradient through evenly spaced colour stops.

    The first column (or row, for vertical) gets the first colour and the last one the
    last colour, measured over the whole rect even where it leaves the canvas; only
    the part on the canvas is painted and the rest is counted in skipped_outside.
    dither="none" mixes the two neighbouring stops per channel, alpha included, rounding
    halves up; indexed sprites then get the nearest palette entry for each mix. A bayer
    dither uses only the stop colours: each pixel takes the next stop when its position
    in the segment (0..1) is above the matrix threshold at its canvas position.
    Without dither, 'transparent' is black with alpha 0, so a gradient to it darkens as
    it fades; use the stop's own colour with alpha 0 (e.g. '#ff000000') to fade only the alpha.
    """
    return {
        **target(layer, frame, create_cel),
        "rect": rect.model_dump(),
        "colors": [rgba(c) for c in colors],
        "direction": direction,
        "dither": MATRIX_SIZE.get(dither, 0),
        "blend": blend,
    }


@op_tool("fill_pattern", mutates=True, batch_hint=True)
def fill_pattern(
    rect: Area,
    color_a: Color,
    color_b: Color,
    density: Annotated[float, Field(ge=0, le=1, description="Share of pixels that get color_b")],
    matrix: Matrix = "bayer4",
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Fill rect with an ordered dither of two colours (clipped to the canvas).

    A pixel gets color_b when the Bayer threshold (v + 0.5) / n^2 at its canvas
    position is below density, color_a otherwise: 0 is all color_a, 1 all color_b.
    The matrix is anchored at canvas (0, 0), so separate fills tile seamlessly; with
    bayer2 and density 0.5, color_b lands where x + y is even.
    """
    return {
        **target(layer, frame, create_cel),
        "rect": rect.model_dump(),
        "color_a": rgba(color_a),
        "color_b": rgba(color_b),
        "density": density,
        "matrix": MATRIX_SIZE[matrix],
        "blend": blend,
    }


def runs_op(
    shapes: list[tuple[RGBA, raster.Rows]], layer: str, frame: int, create_cel: bool, blend: bool
) -> dict[str, Any]:
    """Params for the draw_runs op: one colour per distinct RGBA, runs as "i y x0 x1 ..."."""
    index: dict[RGBA, int] = {}
    runs = []
    for color, rows in shapes:
        i = index.setdefault(color, len(index) + 1)
        runs += [f"{i} {y} {x0} {x1}" for y, spans in rows.items() for x0, x1 in spans]
    return {
        **target(layer, frame, create_cel),
        "colors": [list(color) for color in index],
        "runs": " ".join(runs),
        "blend": blend,
    }


@op_tool("draw_runs", mutates=True, batch_hint=True)
def draw_ascii(
    x: Left,
    y: Top,
    rows: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=256)]],
        Field(min_length=1, max_length=256, description="Art rows, top to bottom"),
    ],
    legend: Annotated[
        dict[str, Color], Field(min_length=1, max_length=256, description="Character -> colour")
    ],
    outline: Annotated[
        Color | None, Field(description="Colour for a 1-pixel ring around the art")
    ] = None,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Draw pixel art written as text; the first character of the first row is at (x, y).

    Each character is one pixel in its legend colour; '.' and ' ' leave the pixel as it
    is and cannot be legend keys. Keys are single characters (any Unicode character).
    Rows may differ in length. outline paints every pixel next to (left, right, above,
    below) a non-transparent art pixel that is not part of the art itself. It overwrites
    pixels there unless blend is true, and ignores art pixels whose colour is transparent. Pixels off the canvas are skipped and counted in skipped_outside;
    painted counts art and outline pixels.

    Example: {"path": "hero.aseprite", "x": 4, "y": 2, "rows": [".aa.", "abba", ".aa."],
    "legend": {"a": "#222034", "b": "#d95763"}, "outline": "#000000"}
    """
    for key in legend:
        if len(key) != 1:
            raise ValueError(f"legend key {key!r} must be a single character")
        if key in raster.UNTOUCHED:
            raise ValueError(
                "'.' and ' ' always leave the pixel untouched; remove them from legend"
            )
    by_char = raster.ascii_art(x, y, rows, legend)
    colors = {char: color_rgba(legend[char]) for char in by_char}
    shapes = [(colors[char], art) for char, art in by_char.items()]
    if outline is not None:
        visible = raster.union(*(art for char, art in by_char.items() if colors[char][3] > 0))
        ring = raster.outline(visible, raster.union(*by_char.values()))
        shapes.append((color_rgba(outline), ring))
    return runs_op(shapes, layer, frame, create_cel, blend)


@op_tool("draw_runs", mutates=True, batch_hint=True)
def draw_isometric_box(
    x: Annotated[Coord, Field(description="x of the top corner of the top face")],
    y: Annotated[Coord, Field(description="y of the top corner of the top face")],
    w: Annotated[int, Field(ge=1, le=128, description="Tiles along the right-going axis")],
    d: Annotated[int, Field(ge=1, le=128, description="Tiles along the left-going axis")],
    h: Annotated[int, Field(ge=0, le=256, description="Height of the side faces in pixels")],
    top: Color,
    left: Color,
    right: Color,
    outline: Annotated[
        Color | None, Field(description="Colour for a 1-pixel ring around the box")
    ] = None,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Draw a 2:1 isometric box: a top face over a left and a right side face.

    (x, y) is the top corner of the top face, the point where pixel (x, y)'s top-left
    corner is; the two topmost pixels are (x - 1, y) and (x, y). From there the top
    face runs w tiles down-right and d tiles down-left, each tile step moving 2 px
    sideways and 1 px down. The left face hangs h px below the lower-left edge
    (2*w px wide), the right face below the lower-right edge (2*d px wide). The box
    covers columns x - 2*d .. x + 2*w - 1 and rows y .. y + w + d + h - 1. A pixel
    belongs to the face that contains its centre, so faces never overlap and leave no
    gaps. outline paints the pixels just outside the box (left, right, above, below).
    w = d = 1 gives only a 2x2 top face; use w and d of 2 or more for a diamond-shaped top.
    Pixels off the canvas are skipped and counted; painted includes the outline.
    """
    faces = raster.isometric_box(x, y, w, d, h)
    shapes = [(color_rgba(c), face) for c, face in zip((top, left, right), faces)]
    if outline is not None:
        box = raster.union(*faces)
        shapes.append((color_rgba(outline), raster.outline(box, box)))
    return runs_op(shapes, layer, frame, create_cel, blend)
