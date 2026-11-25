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
    """Sets pixels as (x, y, r, g, b, a) and reads pixels at (x, y) in frame 1.

    Works on the first layer unless `layer` names another one.
    """

    async def run(
        path: Path, put: Sequence = (), read: Sequence = (), layer: str | None = None
    ) -> list[list[int]]:
        params = {"set": [list(p) for p in put], "get": [list(r) for r in read]}
        if layer is not None:
            params["layer"] = layer
        result = await run_script(
            PIXELS_SCRIPT,
            params,
            settings=ase_settings,
            lock_paths=[path],
            open_file=path,
            save_to=path if put else None,
        )
        return result.data["pixels"]

    return run
