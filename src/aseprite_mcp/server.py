from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from . import __version__
from .config import Settings, load_settings
from .errors import ToolError, describe_invalid
from .preview import preview

INSTRUCTIONS = """\
Draw and animate pixel art in Aseprite files. Every tool works on a file path;
relative paths resolve against ASEPRITE_MCP_ROOT (the server's folder by default).

A good order of work:
1. Plan: canvas size, frame count, palette size. `pixel_art_guide` has short notes.
2. Silhouette: `create_sprite`, then block the shape in one colour with `draw_rect`,
   `draw_ellipse`, `draw_polygon` or `draw_ascii`.
3. Palette: `generate_color_ramp` per material, then `set_palette`.
4. Shading: one light source, base colour plus a shadow and a highlight step;
   `outline` adds a clean edge.
5. Check: look at it with `view_sprite`, find specks with `find_stray_pixels`,
   audit frames with `check_animation`.
6. Export: `export` for PNG/GIF, `export_spritesheet` for game engines.

Conventions:
- Frames, layer stack positions and palette indices count from 1.
- Colours are "#RRGGBB", "#RRGGBBAA" or "transparent".
- Work in .aseprite files. Other formats hold one flat layer with no tags or slices
  (.gif keeps frames), so edits they cannot store are refused.
- Locked layers refuse pixel and cel edits; whole-sprite changes ignore locks.
- Keep layer names unique and without '/': a repeated name finds the shallowest layer
  with it, and a layer named 'x/y' shadows the path 'x/y' of a layer inside group 'x'.
- Use `batch` to apply many edits to one file at once; nothing is saved if one fails.
- Read-only tools (`get_sprite_info`, `read_pixels`, `view_sprite`...) never change
  the file and are safe to call any time.
"""


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[None]:
    try:
        yield
    finally:
        preview.stop()


class _Server(FastMCP):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            return await super().call_tool(name, arguments)
        except ToolError as e:
            if isinstance(e.__cause__, ValidationError):
                problems = describe_invalid(e.__cause__)
                raise ToolError(f"{name}: invalid arguments: {problems}") from None
            raise


mcp = _Server("aseprite", instructions=INSTRUCTIONS, lifespan=_lifespan)
# FastMCP has no setting for this; without it clients see the mcp library's version.
mcp._mcp_server.version = __version__


@cache
def get_settings() -> Settings:
    return load_settings()


# Tool modules register themselves on import and need `mcp` and `get_settings`.
from . import tools

tools.misc.add_lua_tool(mcp, get_settings())
