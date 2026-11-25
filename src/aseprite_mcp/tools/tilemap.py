from typing import Annotated, Any

from pydantic import BaseModel, Field

from .. import colors
from ..models import Pixel, Rect
from ._registry import op_tool
from .layers import LayerRef

MAX_TILES = 4096
# A tile is at most 256x256 (the add_layer limit).
MAX_TILE_PIXELS = 65536

TilemapLayer = Annotated[LayerRef, Field(description="Tilemap layer name or 'group/child' path")]


class TileCell(BaseModel):
    col: Annotated[int, Field(strict=True, ge=0, le=65535)]
    row: Annotated[int, Field(strict=True, ge=0, le=65535)]
    index: Annotated[int, Field(strict=True, ge=0, description="Tile index; 0 is the empty tile")]


def _info_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return {
        "layer": result["layer"],
        "tile_size": result["tile_size"],
        "origin": result["origin"],
        "tile_count": result["tile_count"],
        "grid": result["grid"],
        "cel": result.get("cel"),
        "region": result["region"],
        "tiles": result["tiles"],
        "flags": result.get("flags") or [],
    }


@op_tool("get_tilemap_info", mutates=False, finish=_info_result)
def get_tilemap_info(
    layer: TilemapLayer,
    frame: Annotated[int, Field(ge=1)] = 1,
    rect: Annotated[
        Rect | None,
        Field(description="Cells to read, in tiles: x=col, y=row, w and h; default whole grid"),
    ] = None,
) -> dict[str, Any]:
    """Describe a tilemap layer and read the tile indices placed in a frame.

    The grid is the layer's own tileset grid: tile_size, origin, and the columns and
    rows that cover the canvas. tile_count includes tile 0, the empty tile. cel gives the
    frame's tilemap cel in cells (null without one). tiles holds one list of indices per
    row of the region (0 where nothing is placed); flags lists flipped cells. At most
    4096 cells per call.
    """
    if rect is not None:
        if rect.x < 0 or rect.y < 0:
            raise ValueError("rect starts at col/row 0; negative cells do not exist")
        if rect.w * rect.h > MAX_TILES:
            raise ValueError(
                f"rect covers {rect.w * rect.h} cells; read at most {MAX_TILES} per call"
            )
    return {
        "layer": layer,
        "frame": frame,
        "rect": rect.model_dump() if rect else None,
        "max_cells": MAX_TILES,
    }


@op_tool("draw_tile", mutates=True)
def draw_tile(
    layer: TilemapLayer,
    tile_index: Annotated[
        int,
        Field(ge=1, description="Tile to paint; the tileset's tile count adds a new tile"),
    ],
    pixels: Annotated[list[Pixel], Field(min_length=1, max_length=MAX_TILE_PIXELS)],
) -> dict[str, Any]:
    """Set pixels of one tile in the layer's tileset; x and y are inside the tile.

    Pixels get exactly the given colour (no blending; a later entry wins). Every
    placement of the tile changes, in every tilemap layer sharing the tileset. Tile 0 is
    the empty tile and cannot be painted; passing tile_count appends a new tile.
    """
    return {
        "layer": layer,
        "tile_index": tile_index,
        "pixels": [[p.x, p.y, *colors.parse_color(p.color)] for p in pixels],
    }


@op_tool("set_tiles", mutates=True)
def set_tiles(
    layer: TilemapLayer,
    frame: Annotated[int, Field(ge=1)],
    tiles: Annotated[list[TileCell], Field(min_length=1, max_length=MAX_TILES)],
) -> dict[str, Any]:
    """Place tiles in grid cells (col, row from 0 at the grid origin) of one frame.

    The cel is created or grown as needed. Cells must lie on the canvas grid and indices
    below the tileset's tile_count. A later entry for the same cell wins. A cel linked to
    other frames gets its own copy first.
    """
    return {
        "layer": layer,
        "frame": frame,
        "tiles": [[t.col, t.row, t.index] for t in tiles],
    }
