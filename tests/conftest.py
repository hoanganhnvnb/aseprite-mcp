import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import pytest

from aseprite_mcp import server
from aseprite_mcp.config import Settings, load_settings
from aseprite_mcp.ops import run_ops
from aseprite_mcp.runner import run_script

MakeSprite = Callable[..., Awaitable[Path]]
PIXELS_SCRIPT = Path(__file__).parent / "lua" / "pixels.lua"
CELS_SCRIPT = Path(__file__).parent / "lua" / "cels.lua"
LOCKS_SCRIPT = Path(__file__).parent / "lua" / "locks.lua"
IMAGES_SCRIPT = Path(__file__).parent / "lua" / "images.lua"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "ase_settings" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.aseprite)


@pytest.fixture
def ase_settings(tmp_path: Path) -> Settings:
    settings = load_settings({**os.environ, "ASEPRITE_MCP_ROOT": str(tmp_path)})
    if settings.aseprite is None:
        pytest.skip("Aseprite binary not found (set ASEPRITE_PATH)")
    return settings


@pytest.fixture
def make_sprite(ase_settings: Settings) -> MakeSprite:
    async def make(
        tmp_path: Path,
        w: int = 16,
        h: int = 16,
        mode: str = "rgb",
        layers: Sequence[str] = (),
        name: str = "sprite.aseprite",
    ) -> Path:
        path = tmp_path / name
        create = {"width": w, "height": h, "color_mode": mode, "layers": list(layers)}
        await run_ops(path, [], settings=ase_settings, create=create)
        return path

    return make


@pytest.fixture
def call(ase_settings: Settings, monkeypatch: pytest.MonkeyPatch):
    """Calls a tool the way a client does, arguments validated by the server."""
    monkeypatch.setattr(server, "get_settings", lambda: ase_settings)

    async def call_tool(name: str, /, **args):
        _, structured = await server.mcp.call_tool(name, args)
        return structured

    return call_tool


@pytest.fixture
def pixels(ase_settings: Settings):
    """Sets pixels as (x, y, r, g, b, a) and reads pixels at (x, y) as RGBA.

    Works on frame 1 of the first layer unless `frame` or `layer` say otherwise.
    With `values=True` it returns the stored pixel values (indices on indexed
    sprites, -1 outside the cel) instead of RGBA. `background=True` first turns the
    layer into the background layer (named "Background").
    """

    async def run(
        path: Path,
        put: Sequence = (),
        read: Sequence = (),
        layer: str | None = None,
        frame: int = 1,
        values: bool = False,
        background: bool = False,
    ) -> list:
        params = {"set": [list(p) for p in put], "get": [list(r) for r in read], "frame": frame}
        if layer is not None:
            params["layer"] = layer
        if background:
            params["background"] = True
        result = await run_script(
            PIXELS_SCRIPT,
            params,
            settings=ase_settings,
            lock_paths=[path],
            open_file=path,
            save_to=path if put or background else None,
        )
        return result.data["values" if values else "pixels"]

    return run


@pytest.fixture
def grid(ase_settings: Settings):
    """Returns the canvas of one layer and frame as rows of '#' (painted) and '.'."""

    async def run(path: Path, layer: str | None = None, frame: int = 1) -> list[str]:
        params: dict = {"frame": frame}
        if layer is not None:
            params["layer"] = layer
        result = await run_script(
            PIXELS_SCRIPT, params, settings=ase_settings, lock_paths=[path], open_file=path
        )
        return result.data["grid"]

    return run


@pytest.fixture
def set_palette(ase_settings: Settings):
    """Replaces the palette with the given (r, g, b, a) colours, index 0 first."""

    async def run(path: Path, colors: Sequence) -> None:
        await run_script(
            PIXELS_SCRIPT,
            {"palette": [list(c) for c in colors]},
            settings=ase_settings,
            lock_paths=[path],
            open_file=path,
            save_to=path,
        )

    return run


@pytest.fixture
def cels(ase_settings: Settings):
    """Lists a layer's cel in every frame (False where there is none).

    `update` takes (frame, opacity, z_index) tuples applied before reading.
    """

    async def run(path: Path, layer: str | None = None, update: Sequence = ()) -> list:
        params: dict = {"update": [list(u) for u in update]}
        if layer is not None:
            params["layer"] = layer
        result = await run_script(
            CELS_SCRIPT,
            params,
            settings=ase_settings,
            lock_paths=[path],
            open_file=path,
            save_to=path if update else None,
        )
        return result.data["cels"]

    return run


@pytest.fixture
def locks(ase_settings: Settings):
    """Locks the layers in `lock`, then returns the paths of every locked layer."""

    async def run(path: Path, lock: Sequence[str] = ()) -> list[str]:
        result = await run_script(
            LOCKS_SCRIPT,
            {"lock": list(lock)},
            settings=ase_settings,
            lock_paths=[path],
            open_file=path,
            save_to=path if lock else None,
        )
        return result.data["locked"]

    return run


@pytest.fixture
def images(ase_settings: Settings):
    """Returns a layer's cel in every frame as bounds plus image bytes (False if none)."""

    async def run(path: Path, layer: str | None = None) -> list:
        params = {} if layer is None else {"layer": layer}
        result = await run_script(
            IMAGES_SCRIPT, params, settings=ase_settings, lock_paths=[path], open_file=path
        )
        return result.data["images"]

    return run
