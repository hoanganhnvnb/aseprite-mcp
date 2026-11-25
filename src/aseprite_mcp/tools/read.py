import io
import string
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Image as ImageResult
from mcp.types import TextContent
from PIL import Image
from pydantic import Field

from .. import server, sheet
from ..errors import AsepriteError, ToolError
from ..models import Rect
from ..ops import run_op
from ..paths import resolve_path
from ..ranges import FrameSpec
from ._registry import SpritePath, op_tool

MAX_VIEW_FRAMES = 64
# Pixels rendered for one view_sprite call, onion-skin frames included.
MAX_VIEW_PIXELS = 4096 * 4096

ReadLayer = Annotated[
    str | None,
    Field(
        min_length=1,
        description="Layer name or 'group/child' path for that layer's own pixels; "
        "omit for the visible layers composited",
    ),
]
Frame = Annotated[int, Field(ge=1, description="1-based frame number")]

# Characters for rows output: never '.' or ' ' (draw_ascii leaves those untouched),
# no quotes or backslashes, then Latin letters once ASCII runs out.
ROW_CHARS = (
    string.ascii_uppercase
    + string.ascii_lowercase
    + string.digits
    + "".join(c for c in string.punctuation if c not in ".\"'\\`")
    + "".join(chr(c) for c in range(0xC0, 0x250) if c not in (0xD7, 0xF7))
)


def pixel_hex(value: int) -> str | None:
    """'#rrggbb' or '#rrggbbaa' for a pixel value from Lua, None when transparent."""
    r, g, b, a = value & 255, value >> 8 & 255, value >> 16 & 255, value >> 24 & 255
    if a == 0:
        return None
    return f"#{r:02x}{g:02x}{b:02x}" + ("" if a == 255 else f"{a:02x}")


def format_pixels(data: dict[str, Any], fmt: str) -> dict[str, Any]:
    w = data["w"]
    colors = [pixel_hex(v) for v in data["pixels"]]
    lines = [colors[i : i + w] for i in range(0, len(colors), w)]
    out = {"x": data["x"], "y": data["y"], "w": w, "h": data["h"]}
    if fmt == "json":
        return {**out, "pixels": [[c or "transparent" for c in line] for line in lines]}
    if fmt == "hex":
        return {**out, "rows": [" ".join(c or "." for c in line) for line in lines]}
    chars: dict[str, str] = {}
    for color in colors:
        if color is not None and color not in chars:
            if len(chars) == len(ROW_CHARS):
                raise ToolError(
                    f"the rect has more than {len(ROW_CHARS)} colours, too many for "
                    "format='rows'; use format='hex' or 'json'"
                )
            chars[color] = ROW_CHARS[len(chars)]
    rows = ["".join("." if c is None else chars[c] for c in line) for line in lines]
    return {**out, "rows": rows, "legend": {char: color for color, char in chars.items()}}


def _read_pixels_result(result: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return format_pixels(result, params["format"])


@op_tool("read_pixels", mutates=False, finish=_read_pixels_result)
def read_pixels(
    rect: Rect,
    layer: ReadLayer = None,
    frame: Frame = 1,
    format: Literal["rows", "hex", "json"] = "rows",
) -> dict[str, Any]:
    """Read the pixels in rect; parts outside the canvas read as transparent.

    rows: one character per pixel with a legend of character -> colour, '.' for
    transparent; x, y, rows and legend can be passed to draw_ascii as they are.
    hex: rows of space-separated '#rrggbb'/'#rrggbbaa', '.' for transparent.
    json: pixels as a list of rows of colours or 'transparent'.
    Without layer, the visible layers are composited (layer opacity and blend modes
    applied, hidden layers and groups left out). With layer, that layer's own pixels
    are read, even when it is hidden, without its opacity. Indexed and grayscale
    sprites give their RGBA colours. At most ASEPRITE_MCP_MAX_READ_PIXELS pixels
    (default 65536) per call; use view_sprite to look at larger areas.
    """
    limit = server.get_settings().max_read_pixels
    count = rect.w * rect.h
    if count > limit:
        raise ToolError(
            f"rect is {rect.w}x{rect.h} = {count} pixels; read_pixels returns at most "
            f"{limit}. Read a smaller rect, or use view_sprite to look at the whole sprite"
        )
    return {"rect": rect.model_dump(), "layer": layer, "frame": frame, "format": format}


def _bounds_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return {
        "frames": [{"frame": f["frame"], "bounds": f.get("bounds")} for f in result["frames"]],
        "bounds": result.get("bounds"),
    }


@op_tool("get_bounds", mutates=False, finish=_bounds_result)
def get_bounds(layer: ReadLayer = None, frames: FrameSpec = "all") -> dict[str, Any]:
    """The box around the non-transparent pixels of each frame, and around all of them.

    Bounds are {x, y, w, h} in canvas coordinates, clipped to the canvas; null for an
    empty frame. Without layer the visible composite is measured, with layer that
    layer's own pixels.
    """
    return {"layer": layer, "frames": frames}


def _compare_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    count = result["different_pixels"]
    return {
        "frame_a": result["frame_a"],
        "frame_b": result["frame_b"],
        "identical": count == 0,
        "different_pixels": count,
        "bounds": result.get("bounds"),
        "area": result["area"],
    }


@op_tool("compare_frames", mutates=False, finish=_compare_result)
def compare_frames(
    frame_a: Frame,
    frame_b: Frame,
    layer: ReadLayer = None,
    region: Annotated[
        Rect | None, Field(description="Only compare this canvas rectangle; default all")
    ] = None,
) -> dict[str, Any]:
    """Count the pixels that differ between two frames and box them in.

    A pixel differs when its RGBA differs; two fully transparent pixels are equal.
    bounds is the canvas box around the differences, null when the frames are
    identical. Without layer the visible composites are compared.
    """
    return {
        "frame_a": frame_a,
        "frame_b": frame_b,
        "layer": layer,
        "region": None if region is None else region.model_dump(),
    }


def _stats_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    counted = result["pixels"] - result["transparent"]
    return {
        "frame": result["frame"],
        "pixels": result["pixels"],
        "transparent": result["transparent"],
        "unique": result["unique"],
        "colors": [
            {"color": pixel_hex(value), "count": count, "percent": round(100 * count / counted, 2)}
            for value, count in result["colors"]
        ],
    }


@op_tool("get_color_stats", mutates=False, finish=_stats_result)
def get_color_stats(
    frame: Frame = 1, top: Annotated[int, Field(ge=1, le=256)] = 16
) -> dict[str, Any]:
    """The most used colours of the visible composite of one frame.

    Colours are told apart by their full RGBA, so the same RGB at another alpha is a
    separate entry. Fully transparent pixels are only counted in transparent; unique
    and percent cover the other pixels. Ties are ordered by red, green, blue, then alpha.
    """
    return {"frame": frame, "top": top}


def _stray_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    lone = [{**p, "color": pixel_hex(p["color"])} for p in result["lone_pixels"]]
    clusters = result["small_clusters"]
    return {
        "frame": result["frame"],
        "lone_pixels": lone,
        "lone_pixel_count": result["lone_pixel_count"],
        "lone_pixels_truncated": result["lone_pixel_count"] > len(lone),
        "small_clusters": clusters,
        "small_cluster_count": result["small_cluster_count"],
        "small_clusters_truncated": result["small_cluster_count"] > len(clusters),
    }


@op_tool("find_stray_pixels", mutates=False, finish=_stray_result)
def find_stray_pixels(frame: Frame = 1, layer: ReadLayer = None) -> dict[str, Any]:
    """Find specks: non-transparent pixels cut off from the rest of the art.

    Pixels touching on a side or a corner (8 neighbours) belong together. lone_pixels
    are groups of one pixel, small_clusters groups of two or three, each with its box
    and pixels. Both lists are in reading order and hold at most 50 entries; the
    counts give the totals. Without layer the visible composite is checked.
    """
    return {"frame": frame, "layer": layer}


def _frame_list(frames: list[int]) -> str:
    parts: list[str] = []
    start = prev = frames[0]
    for n in [*frames[1:], None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ",".join(parts)


def _load(path: Path, frame: int) -> Image.Image:
    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except OSError:
        raise AsepriteError(f"Aseprite did not render frame {frame}") from None


@server.mcp.tool(structured_output=False)
async def view_sprite(
    path: SpritePath,
    frames: FrameSpec = 1,
    layer: ReadLayer = None,
    scale: Annotated[
        int | None,
        Field(ge=1, le=sheet.MAX_SCALE, description="Screen pixels per sprite pixel"),
    ] = None,
    grid: Annotated[bool, Field(description="Lines between pixels, from scale 4")] = False,
    rulers: Annotated[bool, Field(description="Canvas coordinates along the edges")] = False,
    region: Annotated[Rect | None, Field(description="Show only this canvas rectangle")] = None,
    onion_skin: Annotated[
        int, Field(ge=0, le=4, description="Previous frames to show faded beneath each frame")
    ] = 0,
) -> list[TextContent | ImageResult]:
    """Look at the sprite: a PNG of the requested frames plus a short description.

    Frames are laid out left to right, then down, over a grey checkerboard that marks
    transparency. Without scale, the largest that keeps the image within 512 px is
    used. The image never exceeds 2048 px per side: a larger scale is reduced, and when
    even scale 1 is too big every n-th pixel is shown; the text says so. Up to 64
    frames per call. Without layer the visible layers are composited; with layer only
    that layer's own pixels are shown. onion_skin shows each frame's previous frames
    beneath it, the nearest at 50% opacity and each older one at half the one after.
    Nothing is saved. Not available in batch.
    """
    settings = server.get_settings()
    target = resolve_path(path, settings, must_exist=True)
    with tempfile.TemporaryDirectory(prefix="aseprite-mcp-view-") as tmp:
        params = {
            "frames": frames,
            "layer": layer,
            "region": None if region is None else region.model_dump(),
            "onion_skin": onion_skin,
            "dir": tmp,
            "max_frames": MAX_VIEW_FRAMES,
            "max_pixels": MAX_VIEW_PIXELS,
        }
        result = await run_op(target, "render_frames", params, settings=settings, mutates=False)
        images = {n: _load(Path(tmp) / f"{n}.png", n) for n in result["rendered"]}

    shown = result["frames"]
    if onion_skin:
        tiles = [
            sheet.onion(
                [images[k] for k in range(n - 1, max(0, n - 1 - onion_skin), -1)], images[n]
            )
            for n in shown
        ]
    else:
        tiles = [images[n] for n in shown]
    area = result["area"]
    picture, layout = sheet.render(tiles, (area["x"], area["y"]), scale, grid, rulers)
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")

    zoom = f"1/{layout.shrink} size" if layout.shrink > 1 else f"scale {layout.scale}"
    which = "frame" if len(shown) == 1 else "frames"
    summary = (
        f"{target.name}: {which} {_frame_list(shown)} of {result['frame_count']}, "
        f"{area['w']}x{area['h']} px at ({area['x']}, {area['y']}), {zoom}, "
        f"{layout.columns} per row; image {picture.width}x{picture.height} px."
    )
    lines = [summary, *layout.notes]
    if layer is not None:
        lines.append(f"Only layer '{layer}'.")
    if onion_skin:
        earlier = "frame" if onion_skin == 1 else f"{onion_skin} frames"
        lines.append(f"Onion skin: the {earlier} before each one shown faded beneath it.")
    return [TextContent(type="text", text="\n".join(lines)), ImageResult(data=buffer.getvalue())]
