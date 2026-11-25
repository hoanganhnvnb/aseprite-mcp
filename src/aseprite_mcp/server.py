from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings
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


mcp = FastMCP("aseprite", instructions=INSTRUCTIONS, lifespan=_lifespan)


@cache
def get_settings() -> Settings:
    return load_settings()


# Tool modules register themselves on import and need `mcp` and `get_settings`.
from . import tools

tools.misc.add_lua_tool(mcp, get_settings())
