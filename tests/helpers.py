import json
from pathlib import Path

from aseprite_mcp.config import Settings

# Tools whose description holds a runnable 'Example:' paragraph.
DOC_EXAMPLE_TOOLS = [
    "draw_pixels",
    "draw_rect",
    "draw_ascii",
    "draw_text",
    "batch",
    "copy_frames",
    "export",
    "read_pixels",
    "view_sprite",
    "set_palette",
]


def rect(x: int, y: int, w: int, h: int) -> dict:
    return {"x": x, "y": y, "w": w, "h": h}


def sprite_maker(width: int, height: int):
    """A new_sprite(call, w, h, ...) helper whose default size suits one test file."""

    async def new_sprite(
        call, w: int = width, h: int = height, *, frames: int = 1, name: str = "a.aseprite", **args
    ) -> None:
        await call("create_sprite", path=name, width=w, height=h, **args)
        if frames > 1:
            await call("add_frames", path=name, count=frames - 1)

    return new_sprite


def make_settings(root: Path, sandbox: bool = False, aseprite: str | None = None) -> Settings:
    return Settings(
        aseprite=aseprite,
        root=root,
        sandbox=sandbox,
        timeout=60.0,
        max_procs=1,
        allow_lua=False,
        max_read_pixels=65536,
    )


def doc_example(description: str) -> dict:
    """The arguments of the 'Example:' paragraph in a tool description."""
    paragraph = description.split("Example:", 1)[1].split("\n\n", 1)[0]
    return json.loads(paragraph)
