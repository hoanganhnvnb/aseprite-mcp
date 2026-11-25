from functools import cache

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings

INSTRUCTIONS = """\
Edit Aseprite sprites stored as files. Every tool takes the sprite file path;
relative paths resolve against the server's root folder.
Start with create_sprite or get_sprite_info, then apply edits.
Use batch to run several edits on one file in a single step: they are applied
together and nothing is saved if any of them fails.
"""

mcp = FastMCP("aseprite", instructions=INSTRUCTIONS)


@cache
def get_settings() -> Settings:
    return load_settings()


# Tool modules register themselves on import and need `mcp` and `get_settings`.
from . import tools  # noqa: F401
