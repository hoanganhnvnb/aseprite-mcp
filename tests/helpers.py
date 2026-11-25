from pathlib import Path

from aseprite_mcp.config import Settings


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
