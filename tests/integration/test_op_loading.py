import dataclasses

import pytest
from mcp.server.fastmcp import FastMCP

from aseprite_mcp import server
from aseprite_mcp.config import Settings
from aseprite_mcp.tools.misc import add_lua_tool

AREA = {"x": 0, "y": 0, "w": 2, "h": 2}

# One call per op file, each the only op of its run, so the file is loaded on its own.
ALONE = [
    ("cels.lua", "clear_cels", {"layer": "Layer 1", "frames": "1"}, "removed"),
    ("color.lua", "get_palette", {}, "colors"),
    (
        "draw.lua",
        "draw_ascii",
        {"x": 0, "y": 0, "rows": ["a"], "legend": {"a": "#ff0000"}},
        "painted",
    ),
    ("export.lua", "export_spritesheet", {"output": "sheet.png"}, "files"),
    ("frames.lua", "add_frames", {"count": 1}, "frames"),
    ("layers.lua", "add_layer", {"name": "top"}, "layer"),
    ("quality.lua", "check_animation", {}, "ok"),
    ("read.lua", "get_bounds", {}, "frames"),
    ("region.lua", "erase_region", {"layer": "Layer 1", "rect": AREA}, "erased_frames"),
    ("slices.lua", "list_slices", {}, "slices"),
    ("sprite.lua", "get_sprite_info", {}, "width"),
    ("transform.lua", "flip", {"axis": "horizontal"}, "frames"),
]


@pytest.mark.parametrize(("file", "tool", "args", "key"), ALONE, ids=[c[0] for c in ALONE])
async def test_op_file_works_on_its_own(call, file, tool, args, key):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    result = await call(tool, path="a.aseprite", **args)

    assert key in result


async def test_tilemap_op_works_on_its_own(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await call("add_layer", path="a.aseprite", name="Floor", kind="tilemap", tile_size=4)

    result = await call("get_tilemap_info", path="a.aseprite", layer="Floor")

    assert result["tile_size"] == {"w": 4, "h": 4}


async def test_run_lua_can_call_ops_from_any_file(
    ase_settings: Settings, monkeypatch: pytest.MonkeyPatch, make_sprite, tmp_path
):
    settings = dataclasses.replace(ase_settings, allow_lua=True)
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    app = FastMCP("lua-test")
    add_lua_tool(app, settings)
    path = await make_sprite(tmp_path, w=8, h=6)

    _, result = await app.call_tool(
        "run_lua",
        {"path": str(path), "script": "return OPS.sprite_info({ spr = sprite }, {}).height"},
    )

    assert result["result"] == 6
