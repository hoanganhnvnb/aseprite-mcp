import json
import warnings

import pytest

from aseprite_mcp.colors import PALETTES
from aseprite_mcp.errors import ToolError
from aseprite_mcp.server import mcp
from aseprite_mcp.tools._registry import BATCHABLE, batch_op
from aseprite_mcp.tools.color import CONVOLUTION_MATRICES


async def _schema(name: str) -> dict:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    return tools[name].inputSchema


async def test_palettes_resource_lists_the_presets():
    [content] = await mcp.read_resource("aseprite://palettes")

    assert content.mime_type == "application/json"
    data = json.loads(content.content)
    assert list(data) == list(PALETTES)
    assert data["gameboy"] == ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"]


async def test_set_palette_preset_enum_comes_from_the_presets():
    preset = (await _schema("set_palette"))["properties"]["preset"]["anyOf"][0]

    assert preset["enum"] == list(PALETTES)


async def test_set_palette_over_256_rejected():
    with pytest.raises(ToolError, match="256"):
        await mcp.call_tool("set_palette", {"path": "a.aseprite", "colors": ["#000000"] * 257})


def test_set_palette_needs_colors_or_preset(tmp_path):
    with pytest.raises(ToolError, match="exactly one"):
        batch_op(1, "set_palette", {}, tmp_path / "a.aseprite")


def test_set_palette_refuses_colors_and_preset_together(tmp_path):
    args = {"colors": ["#000000"], "preset": "pico8"}

    with pytest.raises(ToolError, match="exactly one"):
        batch_op(1, "set_palette", args, tmp_path / "a.aseprite")


def test_adjust_colors_needs_a_change(tmp_path):
    with pytest.raises(ToolError, match="nothing to change"):
        batch_op(1, "adjust_colors", {"layer": "Layer 1"}, tmp_path / "a.aseprite")


async def test_adjust_colors_hue_range():
    with pytest.raises(ToolError, match="180"):
        await mcp.call_tool("adjust_colors", {"path": "a.aseprite", "layer": "Layer 1", "hue": 181})


async def test_replace_colors_tolerance_range():
    mapping = {"from": "#ff0000", "to": "#0000ff"}
    with pytest.raises(ToolError, match="255"):
        await mcp.call_tool(
            "replace_colors",
            {"path": "a.aseprite", "layer": "L", "mappings": [mapping], "tolerance": 256},
        )


async def test_convolution_matrix_enum():
    matrix = (await _schema("apply_convolution"))["properties"]["matrix"]

    assert matrix["enum"] == list(CONVOLUTION_MATRICES)
    assert "blur-3x3" in matrix["enum"]
    assert len(matrix["enum"]) == 39


async def test_outline_schema_defaults():
    props = (await _schema("outline"))["properties"]

    assert props["place"]["enum"] == ["outside", "inside"]
    assert props["matrix"]["enum"] == ["circle", "square", "horizontal", "vertical"]
    assert props["matrix"]["default"] == "circle"


def test_color_tools_are_batchable():
    for name in (
        "set_palette",
        "replace_colors",
        "adjust_colors",
        "outline",
        "apply_convolution",
        "quantize_to_palette",
    ):
        assert BATCHABLE[name][:2] == (name, True)
    assert BATCHABLE["get_palette"][:2] == ("get_palette", False)
    assert BATCHABLE["extract_palette"][:2] == ("extract_palette", False)
    assert "generate_color_ramp" not in BATCHABLE


def test_replace_colors_batch_args_use_from_and_to(tmp_path):
    args = {"layer": "L", "mappings": [{"from": "#ff0000", "to": "transparent"}]}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        op = batch_op(1, "replace_colors", args, tmp_path / "a.aseprite")

    assert op.params["mappings"] == [{"from": [255, 0, 0, 255], "to": [0, 0, 0, 0]}]


async def test_generate_color_ramp_tool():
    _, structured = await mcp.call_tool(
        "generate_color_ramp", {"base_color": "#808080", "steps": 3}
    )

    assert structured == {"result": ["#1a1a1a", "#808080", "#e6e6e6"]}


async def test_generate_color_ramp_steps_limit():
    with pytest.raises(ToolError, match="16"):
        await mcp.call_tool("generate_color_ramp", {"base_color": "#808080", "steps": 17})
