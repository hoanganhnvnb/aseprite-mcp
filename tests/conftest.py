import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import pytest

from aseprite_mcp.config import Settings, load_settings
from aseprite_mcp.ops import run_ops

MakeSprite = Callable[..., Awaitable[Path]]


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
