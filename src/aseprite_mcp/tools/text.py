import os
import sys
from itertools import groupby
from typing import Annotated, Any, Literal

from PIL import Image
from pydantic import Field

from .. import fonts, raster, server
from ..colors import RGBA, color_rgba
from ..models import Color, Coord
from ._registry import READ_ONLY, op_tool
from .draw import Blend, CreateCel, DrawFrame, DrawLayer, runs_op

Text = Annotated[
    str,
    # The 2000 character limit applies after "\r\n" becomes "\n", in render_text.
    Field(
        min_length=1,
        max_length=2 * fonts.MAX_CHARS,
        description="Text, at most 2000 characters; '\\n' starts a new line",
    ),
]
FontName = Annotated[
    str | None,
    Field(
        description="Font name from list_fonts (family, 'Family Style' or file name, any "
        "case) or an absolute path to a .ttf/.otf/.ttc file; empty = the built-in font"
    ),
]
Size = Annotated[
    int, Field(ge=1, le=fonts.MAX_SIZE, description="Font size in pixels (FreeType pixel size)")
]
Bold = Annotated[bool, Field(description="Thicken the glyphs by 1 px to the right")]
LetterSpacing = Annotated[int, Field(ge=-8, le=32, description="Extra px between characters")]
LineSpacing = Annotated[int, Field(ge=-64, le=256, description="Extra px between lines")]
ShadowX = Annotated[
    int,
    Field(ge=-fonts.MAX_SHADOW, le=fonts.MAX_SHADOW, description="Shadow offset to the right"),
]
ShadowY = Annotated[
    int, Field(ge=-fonts.MAX_SHADOW, le=fonts.MAX_SHADOW, description="Shadow offset downwards")
]
Anchor = Literal[
    "top_left",
    "top",
    "top_right",
    "left",
    "center",
    "right",
    "bottom_left",
    "bottom",
    "bottom_right",
]


def pick_font(name: str | None, size: int) -> fonts.Font:
    if name is None or not name.strip():
        return fonts.load_font(None, size)
    entries = fonts.installed_fonts(fonts.font_dirs(sys.platform, os.environ))
    return fonts.load_font(fonts.find_font(name, entries, server.get_settings()), size)


def anchored(x: int, y: int, w: int, h: int, anchor: str) -> tuple[int, int]:
    """Top-left pixel of a w x h box whose anchor pixel is (x, y)."""
    col = 0 if anchor.endswith("left") else 2 if anchor.endswith("right") else 1
    row = 0 if anchor.startswith("top") else 2 if anchor.startswith("bottom") else 1
    return x - (w - 1) * col // 2, y - (h - 1) * row // 2


def image_runs(image: Image.Image, left: int, top: int) -> list[tuple[RGBA, raster.Rows]]:
    """Horizontal runs of equal colour, skipping fully transparent pixels."""
    by_color: dict[RGBA, raster.Rows] = {}
    data = image.tobytes()
    stride = image.width * 4
    for row in range(image.height):
        line = data[row * stride : (row + 1) * stride]
        pixels = [line[i : i + 4] for i in range(0, stride, 4)]
        x = left
        for value, group in groupby(pixels):
            n = len(list(group))
            if value[3]:
                color = (value[0], value[1], value[2], value[3])
                by_color.setdefault(color, {}).setdefault(top + row, []).append((x, x + n - 1))
            x += n
    return list(by_color.items())


@server.mcp.tool(annotations=READ_ONLY)
def list_fonts(
    query: Annotated[
        str | None, Field(description="Only fonts whose name or file name contains this")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Most fonts to list")] = 100,
) -> dict[str, Any]:
    """List installed fonts usable as draw_text's font, sorted by name.

    Searches the system font folders and ASEPRITE_MCP_FONT_DIRS (folders separated
    like PATH). total counts every match, fonts holds the first `limit` of them.
    """
    dirs = fonts.font_dirs(sys.platform, os.environ)
    entries = fonts.installed_fonts(dirs)
    if query:
        key = query.casefold()
        entries = [e for e in entries if key in e.name.casefold() or key in e.path.name.casefold()]
    return {
        "total": len(entries),
        "fonts": [
            {"name": e.name, "family": e.family, "style": e.style, "path": str(e.path)}
            for e in entries[:limit]
        ],
        "dirs": [str(d) for d in dirs],
        "default": "Leave font empty to use the font built into Pillow",
    }


@server.mcp.tool(annotations=READ_ONLY)
def measure_text(
    text: Text,
    font: FontName = None,
    size: Size = 16,
    bold: Bold = False,
    letter_spacing: LetterSpacing = 0,
    line_spacing: LineSpacing = 0,
    outline_width: Annotated[
        int, Field(ge=0, le=fonts.MAX_OUTLINE, description="Outline thickness; 0 for none")
    ] = 0,
    shadow_dx: ShadowX = 0,
    shadow_dy: ShadowY = 0,
) -> dict[str, Any]:
    """Size in pixels that draw_text would paint for this text, without a sprite.

    outline_width 0 means no outline, shadow offsets 0, 0 no shadow. Antialiasing can
    change the size by a pixel, so this matches draw_text with antialias=false.
    """
    image = fonts.render_text(
        text,
        pick_font(font, size),
        (255, 255, 255, 255),
        bold=bold,
        outline=(0, 0, 0, 255) if outline_width else None,
        outline_width=max(outline_width, 1),
        shadow=(0, 0, 0, 255) if (shadow_dx, shadow_dy) != (0, 0) else None,
        shadow_dx=shadow_dx,
        shadow_dy=shadow_dy,
        letter_spacing=letter_spacing,
        line_spacing=line_spacing,
    )
    return {
        "width": image.width,
        "height": image.height,
        "lines": fonts.normalize_newlines(text).count("\n") + 1,
    }


@op_tool("draw_text", mutates=True)
def draw_text(
    text: Text,
    x: Annotated[Coord, Field(description="Canvas x of the anchor point")],
    y: Annotated[Coord, Field(description="Canvas y of the anchor point")],
    color: Color,
    font: FontName = None,
    size: Size = 16,
    anchor: Annotated[
        Anchor,
        Field(description="Which pixel of the text's bounding box lands on (x, y)"),
    ] = "top_left",
    bold: Bold = False,
    antialias: Annotated[
        bool,
        Field(description="Keep smooth, partly transparent glyph edges; false = crisp pixels"),
    ] = False,
    outline: Annotated[
        Color | None, Field(description="Colour of a ring around the glyphs")
    ] = None,
    outline_width: Annotated[
        int, Field(ge=1, le=fonts.MAX_OUTLINE, description="Outline thickness in pixels")
    ] = 1,
    shadow: Annotated[Color | None, Field(description="Colour of a drop shadow")] = None,
    shadow_dx: ShadowX = 1,
    shadow_dy: ShadowY = 1,
    letter_spacing: LetterSpacing = 0,
    line_spacing: LineSpacing = 0,
    layer: DrawLayer = "",
    frame: DrawFrame = 1,
    create_cel: CreateCel = True,
    blend: Blend = False,
) -> dict[str, Any]:
    """Render text with a font and paint it onto a layer.

    The text's bounding box is the smallest box around every painted pixel (glyphs,
    outline and shadow); anchor picks which of its pixels is placed at (x, y). For an
    even width or height the centre pixel is the one left of or above the middle.
    measure_text gives the box size.
    Without antialias every pixel gets exactly color (or outline/shadow); with it,
    edge pixels are partly transparent: blend=false stores them as they are,
    blend=true mixes them over the layer. Indexed sprites take the nearest palette
    colour (partly transparent edges become opaque there, so keep antialias off).
    Pixels off the canvas are skipped and counted in skipped_outside. Text is at most
    2000 characters and 2048x2048 px. Colour emoji are not supported; characters the
    font lacks show its fallback glyph.
    """
    image = fonts.render_text(
        text,
        pick_font(font, size),
        color_rgba(color),
        bold=bold,
        antialias=antialias,
        outline=color_rgba(outline) if outline is not None else None,
        outline_width=outline_width,
        shadow=color_rgba(shadow) if shadow is not None else None,
        shadow_dx=shadow_dx,
        shadow_dy=shadow_dy,
        letter_spacing=letter_spacing,
        line_spacing=line_spacing,
    )
    left, top = anchored(x, y, image.width, image.height, anchor)
    params = runs_op(image_runs(image, left, top), layer, frame, create_cel, blend)
    return {**params, "width": image.width, "height": image.height}
