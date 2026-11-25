from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from .. import server
from ..colors import parse_color
from ..errors import ToolError
from ..models import Color, Rect
from ..ops import Op, run_ops
from ..paths import check_save_extension, resolve_path
from ._registry import SpritePath, op_tool

MAX_CANVAS = 4096

CanvasSize = Annotated[int, Field(ge=1, le=MAX_CANVAS)]
ColorMode = Literal["rgb", "grayscale", "indexed"]


def _new_sprite_path(path: str, overwrite: bool) -> Path:
    target = resolve_path(path, server.get_settings(), must_exist=False)
    if target.is_dir():
        raise ToolError(f"{target} is a folder")
    if target.exists() and not overwrite:
        raise ToolError(f"{target} already exists; pass overwrite=true to replace it")
    if not target.parent.is_dir():
        raise ToolError(f"Folder does not exist: {target.parent}")
    check_save_extension(target)
    return target


@server.mcp.tool()
async def create_sprite(
    path: SpritePath,
    width: CanvasSize,
    height: CanvasSize,
    color_mode: ColorMode = "rgb",
    background: Color | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a sprite file with one layer and one frame and return its info.

    The format follows the extension (.aseprite keeps layers and frames). The folder must
    already exist. Without a background the layer is transparent.
    """
    target = _new_sprite_path(path, overwrite)
    create: dict[str, Any] = {"width": width, "height": height, "color_mode": color_mode}
    if background is not None:
        create["background"] = list(parse_color(background))
    [info] = await run_ops(
        target,
        [Op("sprite_info", {}, mutates=False)],
        settings=server.get_settings(),
        create=create,
    )
    return {"path": str(target), **info}


@op_tool("sprite_info", mutates=False)
def get_sprite_info() -> dict[str, Any]:
    """Size, color mode, palette size, frames with durations, layer tree, tags and slice count."""
    return {}


@op_tool("set_color_mode", mutates=True)
def set_color_mode(mode: ColorMode) -> dict[str, Any]:
    """Convert the sprite to rgb, grayscale or indexed.

    Indexed uses the sprite's current palette without dithering; colours missing from
    the palette map to the nearest entry. Index 0 becomes the transparent colour: when
    the palette is full, its least used entry is dropped to make room and reported in
    dropped_palette_entries.
    """
    return {"mode": mode}


@op_tool("resize_sprite", mutates=True)
def resize_sprite(width: CanvasSize, height: CanvasSize) -> dict[str, Any]:
    """Scale the whole sprite (every layer and frame) to a new size, nearest-neighbour."""
    return {"width": width, "height": height}


@op_tool("crop_sprite", mutates=True)
def crop_sprite(rect: Rect) -> dict[str, Any]:
    """Crop the canvas to rect in every layer and frame; rect must overlap the canvas."""
    if rect.w > MAX_CANVAS or rect.h > MAX_CANVAS:
        raise ValueError(f"crop size {rect.w}x{rect.h} exceeds {MAX_CANVAS}x{MAX_CANVAS}")
    return {"rect": rect.model_dump()}


@op_tool("save_copy", mutates=False, writes="output")
def save_copy(output: str, overwrite: bool = False) -> dict[str, Any]:
    """Write a copy of the sprite to another file, leaving the source untouched.

    The format follows the output extension (.aseprite, .png, .gif, ...); a multi-frame
    sprite needs .aseprite or .gif. The output folder must exist.
    """
    # The registry resolves output and applies overwrite (see op_tool's `writes`).
    return {"output": output}
