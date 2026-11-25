from typing import Annotated, Any

from pydantic import Field

from ..colors import parse_color
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
        description="false: pixels get exactly this colour (transparent erases); "
        "true: the colour is alpha-blended over what is there"
    ),
]
Thickness = Annotated[int, Field(ge=1, le=64)]


def rgba(color: str) -> list[int]:
    return list(parse_color(color))


def target(layer: str, frame: int, create_cel: bool) -> dict[str, Any]:
    return {"layer": layer, "frame": frame, "create_cel": create_cel}


def points_list(points: list[Point]) -> list[list[int]]:
    return [[p.x, p.y] for p in points]


@op_tool("draw_pixels", mutates=True)
def draw_pixels(
    pixels: Annotated[list[Pixel], Field(min_length=1, max_length=MAX_PIXELS)],
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
) -> dict[str, Any]:
    """Set individual pixels to exact colours (no blending; a later entry wins).

    Pixels outside the canvas are skipped and counted in skipped_outside. The cel grows
    to take in pixels outside it; content beyond the canvas is kept. Works on every
    colour mode: indexed sprites get the nearest palette entry, 'transparent' writes
    the transparent index. On a background layer of an indexed sprite 'transparent'
    becomes the nearest palette colour; RGB and grayscale store it as given.
    """
    return {
        **target(layer, frame, create_cel),
        "pixels": [[p.x, p.y, *rgba(p.color)] for p in pixels],
    }


@op_tool("draw_line", mutates=True)
def draw_line(
    points: Annotated[list[Point], Field(min_length=2, max_length=MAX_POINTS)],
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


@op_tool("draw_rect", mutates=True)
def draw_rect(
    rect: Rect,
    color: Color,
    fill: bool = False,
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
    """
    return {
        **target(layer, frame, create_cel),
        "rect": rect.model_dump(),
        "color": rgba(color),
        "fill": fill,
        "thickness": thickness,
        "blend": blend,
    }


@op_tool("draw_ellipse", mutates=True)
def draw_ellipse(
    cx: Coord,
    cy: Coord,
    rx: Annotated[int, Field(ge=0, le=4096)],
    ry: Annotated[int, Field(ge=0, le=4096)],
    color: Color,
    fill: bool = False,
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


@op_tool("draw_polygon", mutates=True)
def draw_polygon(
    points: Annotated[list[Point], Field(min_length=3, max_length=MAX_POINTS)],
    color: Color,
    fill: bool = True,
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


@op_tool("fill_area", mutates=True)
def fill_area(
    x: Coord,
    y: Coord,
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
