from aseprite_mcp.server import mcp
from aseprite_mcp.tools._registry import BATCHABLE


async def _schema(name: str) -> dict:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    return tools[name].inputSchema


async def test_wrapped_tool_schema_keeps_builder_parameters():
    schema = await _schema("resize_sprite")

    assert schema["required"] == ["path", "width", "height"]
    assert schema["properties"]["width"]["minimum"] == 1
    assert schema["properties"]["width"]["maximum"] == 4096


async def test_wrapped_tool_keeps_docstring():
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert "nearest-neighbour" in tools["resize_sprite"].description


async def test_wrapped_tool_schema_has_nested_rect():
    schema = await _schema("crop_sprite")

    assert schema["required"] == ["path", "rect"]
    assert "Rect" in schema["$defs"]


def test_single_op_tools_are_batchable():
    assert BATCHABLE["resize_sprite"][:2] == ("resize_sprite", True)
    assert BATCHABLE["get_sprite_info"][:2] == ("sprite_info", False)
    assert "save_copy" in BATCHABLE


def test_create_sprite_and_batch_are_not_batchable():
    assert "create_sprite" not in BATCHABLE
    assert "batch" not in BATCHABLE


async def test_internal_ping_is_not_a_tool():
    names = {tool.name for tool in await mcp.list_tools()}

    assert "_ping" not in names
    assert {"create_sprite", "batch", "set_color_mode"} <= names
