import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import server
from ..colors import PALETTES, PaletteName, generate_ramp, parse_color
from ..errors import ToolError
from ..models import Color, Rect
from ..ranges import FrameSpec
from ._registry import READ_ONLY, op_tool
from .layers import LayerRef

# The matrices Aseprite ships in data/convmatr.def, in file order.
CONVOLUTION_MATRICES = (
    "brightness",
    "contrast",
    "negative",
    "blur-3x3",
    "blur-3x3-hard",
    "blur-5x5",
    "blur-7x7",
    "blur-9x9",
    "blur-17x17",
    "blur-5x3-left",
    "blur-17x3-left",
    "blur-3x17-top",
    "blur-5x5-diagonal(\\)",
    "blur-5x5-diagonal(/)",
    "sharpen-3x3",
    "sharpen-5x5",
    "sharpen-7x7",
    "edges-find",
    "edges-find-horizontal",
    "edges-find-vertical",
    "misc-contour",
    "misc-texturize",
    "misc-emboss",
    "misc-marmolize",
    "misc-rock",
    "misc-rock-edges",
    "drunk-3x3_x",
    "drunk-3x3_+",
    "drunk-5x5_x",
    "drunk-5x5_+",
    "drunk-7x7_x",
    "drunk-7x7_+",
    "drunk-9x9_x",
    "drunk-9x9_+",
    "drunk-17x17_x",
    "drunk-17x17_+",
    "drunk-17x17_o",
    "outline-transparent-layer-(cross)",
    "outline-transparent-layer-(square)",
)
ConvolutionMatrix = Literal[CONVOLUTION_MATRICES]  # type: ignore[valid-type]

Region = Annotated[
    Rect | None,
    Field(description="Only change pixels inside this canvas rectangle; default the whole cel"),
]
Percent = Annotated[int, Field(ge=-100, le=100)]


class ColorMapping(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: Color = Field(alias="from")
    to: Color


def rgba(color: str) -> list[int]:
    return list(parse_color(color))


def region_param(region: Rect | None) -> dict[str, int] | None:
    return None if region is None else region.model_dump()


@server.mcp.resource(
    "aseprite://palettes",
    name="palettes",
    description="Preset palettes for set_palette: name -> list of '#rrggbb' colours",
    mime_type="application/json",
)
def palettes() -> str:
    return json.dumps(PALETTES)


@op_tool("get_palette", mutates=False)
def get_palette() -> dict[str, Any]:
    """The sprite's palette as '#rrggbb' colours ('#rrggbbaa' when not opaque).

    Indexed sprites also report transparent_index, the 1-based entry that is
    transparent on normal layers.
    """
    return {}


@op_tool("set_palette", mutates=True)
def set_palette(
    colors: Annotated[
        list[Color] | None, Field(min_length=1, max_length=256, description="1 to 256 colours")
    ] = None,
    preset: Annotated[
        PaletteName | None, Field(description="A preset palette, see aseprite://palettes")
    ] = None,
) -> dict[str, Any]:
    """Replace the palette with the given colours or a preset; pass exactly one of them.

    Colours may carry alpha and may be 'transparent'. RGB pixels do not change.
    Indexed pixels keep their indices, so each shows the new colour at its entry; the
    palette must stay large enough for every index in use, and the transparent index
    stays the same. Grayscale sprites are refused: Aseprite always gives them the 256
    grays, so convert to rgb or indexed with set_color_mode first.
    """
    if (colors is None) == (preset is None):
        raise ValueError("pass exactly one of colors and preset")
    chosen = PALETTES[preset] if preset is not None else colors
    return {"colors": [rgba(c) for c in chosen or []]}


@server.mcp.tool(annotations=READ_ONLY)
def generate_color_ramp(
    base_color: Color,
    steps: Annotated[int, Field(ge=2, le=16, description="Number of colours in the ramp")] = 5,
    hue_shift: Annotated[
        float,
        Field(ge=0, le=60, description="Degrees the hue turns per step away from the base"),
    ] = 0,
    lightness_range: Annotated[
        tuple[Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=1)]],
        Field(description="Lightness (0..1) of the darkest and lightest step"),
    ] = (0.1, 0.9),
) -> list[str]:
    """Shades of base_color from dark to light as '#rrggbb', for set_palette or drawing.

    The base colour itself is one of the steps, placed where its HSL lightness falls
    in lightness_range (the range widens to reach it); the other steps are evenly
    spaced in lightness on each side and keep its saturation. With hue_shift, darker
    steps turn towards blue and lighter ones towards yellow, as pixel artists do for
    shadows and highlights. Alpha in base_color is ignored.
    """
    try:
        return generate_ramp(base_color, steps, hue_shift, lightness_range)
    except ValueError as e:
        raise ToolError(str(e)) from None


@op_tool("replace_colors", mutates=True)
def replace_colors(
    layer: LayerRef,
    mappings: Annotated[
        list[ColorMapping],
        Field(min_length=1, max_length=256, description='[{"from": colour, "to": colour}]'),
    ],
    frames: FrameSpec = 1,
    tolerance: Annotated[
        int,
        Field(ge=0, le=255, description="Largest difference per channel (r, g, b, a) that matches"),
    ] = 0,
    region: Region = None,
) -> dict[str, Any]:
    """Replace colours in a layer, all mappings at once (A->B with B->A swaps them).

    A pixel matches a mapping when each of r, g, b and alpha is within tolerance of
    `from`; fully transparent pixels count as 'transparent' whatever their colour. The
    first matching mapping wins. to='transparent' erases, except on a background layer,
    which ignores alpha and gets opaque black. On indexed sprites pixels are matched by
    their palette colour and get the palette entry nearest to `to` (exactly `to` when
    the palette has it); the palette is not changed. On grayscale sprites pixels compare
    as (v, v, v), so a coloured `from` only matches within tolerance, and `to` is
    stored as its gray value.
    Frames without a cel are skipped. Linked cels change once; one also linked to
    frames outside the list gets its own copy, only when some of its pixels change.
    replaced counts the pixels that matched.
    """
    return {
        "layer": layer,
        "frames": frames,
        "mappings": [{"from": rgba(m.from_), "to": rgba(m.to)} for m in mappings],
        "tolerance": tolerance,
        "region": region_param(region),
    }


@op_tool("adjust_colors", mutates=True)
def adjust_colors(
    layer: LayerRef,
    frames: FrameSpec = 1,
    region: Region = None,
    hue: Annotated[int, Field(ge=-180, le=180, description="Degrees to turn the hue")] = 0,
    saturation: Annotated[Percent, Field(description="Saturation change, -100..100")] = 0,
    lightness: Annotated[Percent, Field(description="Lightness change, -100..100")] = 0,
    brightness: Annotated[Percent, Field(description="Brightness change, -100..100")] = 0,
    contrast: Annotated[Percent, Field(description="Contrast change, -100..100")] = 0,
    invert: Annotated[bool, Field(description="Invert the RGB channels")] = False,
) -> dict[str, Any]:
    """Adjust the colours of a layer with Aseprite's filters; alpha is never changed.

    They run in this order: hue/saturation/lightness (HSL, as percentages), then
    brightness/contrast, then invert.

    Every requested frame must have a cel. A filter removes a cel it leaves fully
    transparent, so a later op on that frame in the same batch finds no cel. Linked
    cels change once; one also linked to frames outside the list always gets its own
    copy, even when nothing changes. Indexed sprites only support invert
    (each pixel gets the palette entry nearest to its inverted colour): the other
    adjustments would rewrite the shared palette.
    """
    if not (hue or saturation or lightness or brightness or contrast or invert):
        raise ValueError(
            "nothing to change: set hue, saturation, lightness, brightness, contrast or invert"
        )
    return {
        "layer": layer,
        "frames": frames,
        "region": region_param(region),
        "hue": hue,
        "saturation": saturation,
        "lightness": lightness,
        "brightness": brightness,
        "contrast": contrast,
        "invert": invert,
    }


@op_tool("outline", mutates=True)
def outline(
    layer: LayerRef,
    color: Color,
    frames: FrameSpec = 1,
    place: Annotated[
        Literal["outside", "inside"],
        Field(
            description="outside: paint the transparent pixels around shapes; "
            "inside: recolour the shapes' own edge pixels"
        ),
    ] = "outside",
    matrix: Annotated[
        Literal["circle", "square", "horizontal", "vertical"],
        Field(description="Which neighbours count: circle = 4 sides, square = all 8"),
    ] = "circle",
    region: Region = None,
) -> dict[str, Any]:
    """Draw a one-pixel outline around the non-transparent shapes of a layer.

    Uses Aseprite's Outline filter; the cel grows to make room. With region only
    pixels inside it change. Background layers are refused (nothing is transparent
    there). Every requested frame must have a cel; an emptied cel (inside outline
    with a transparent color) is removed, and linked cels are handled like
    adjust_colors. Indexed sprites use the palette entry nearest to color.
    """
    return {
        "layer": layer,
        "frames": frames,
        "color": rgba(color),
        "place": place,
        "matrix": matrix,
        "region": region_param(region),
    }


@op_tool("apply_convolution", mutates=True)
def apply_convolution(
    layer: LayerRef,
    matrix: Annotated[ConvolutionMatrix, Field(description="Which convolution matrix to run")],
    frames: FrameSpec = 1,
    region: Region = None,
) -> dict[str, Any]:
    """Run one of Aseprite's convolution matrices (blur, sharpen, edges...) on a layer.

    Alpha is filtered too, except on a background layer, which stays opaque. Indexed
    pixels are filtered through their palette colours and get the nearest entry. A cel
    left fully transparent is removed, so a later op on that frame in the same batch
    finds no cel. Every requested frame must have a cel; linked cels are handled like
    adjust_colors.
    """
    return {"layer": layer, "frames": frames, "matrix": matrix, "region": region_param(region)}


@op_tool("quantize_to_palette", mutates=True)
def quantize_to_palette(layer: LayerRef, frames: FrameSpec = 1) -> dict[str, Any]:
    """Snap every visible pixel of a layer of an RGB sprite to its nearest palette colour.

    Nearest is by RGB distance among the palette's non-transparent entries; each pixel
    keeps its alpha. Indexed sprites (pixels are palette entries already) and grayscale
    sprites (their palette is always the 256 grays) are refused. Frames without a cel
    are skipped. Linked cels are handled like replace_colors. changed counts the pixels
    that got a new value.
    """
    return {"layer": layer, "frames": frames}


@op_tool("extract_palette", mutates=False)
def extract_palette(
    max_colors: Annotated[
        int, Field(ge=2, le=256, description="Most colours to return, counting a transparent slot")
    ] = 16,
    with_alpha: Annotated[
        bool, Field(description="Keep semi-transparent colours apart instead of opaque")
    ] = False,
) -> dict[str, Any]:
    """Find up to max_colors colours that best represent the visible sprite.

    Uses Aseprite's colour quantization over all visible layers and frames. Its
    palettes hold a transparent entry, which is left out of the result but takes one
    of the 256 slots, so max_colors=256 gives at most 255 colours. The
    sprite and its palette are not changed: pass the result to set_palette to use it.
    """
    return {"max_colors": max_colors, "with_alpha": with_alpha}
