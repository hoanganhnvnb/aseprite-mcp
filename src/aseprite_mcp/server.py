from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings
from .preview import preview

INSTRUCTIONS = """\
Edit Aseprite sprites stored as files. Every tool takes the sprite file path;
relative paths resolve against the server's root folder.
Start with create_sprite or get_sprite_info, then apply edits.
Use batch to run several edits on one file in a single step: they are applied
together and nothing is saved if any of them fails.
To show results in a browser, export into a folder and call start_preview on it.
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
from . import tools  # noqa: F401
