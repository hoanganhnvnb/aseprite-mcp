from pathlib import Path
from typing import Any

import pytest

from aseprite_mcp import server
from aseprite_mcp.config import load_settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.server import mcp
from aseprite_mcp.tools._registry import BATCHABLE, op_tool


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


@op_tool("save_copy", mutates=False, writes="output")
def write_raw_output(output: str) -> dict[str, Any]:
    """Test-only tool whose builder passes the output path through untouched."""
    return {"output": output}


@pytest.fixture
def sandboxed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / "s.aseprite").write_bytes(b"not opened")
    settings = load_settings({"ASEPRITE_MCP_ROOT": str(root), "ASEPRITE_MCP_SANDBOX": "1"})
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    return root


async def test_registry_refuses_output_outside_sandbox(sandboxed: Path):
    with pytest.raises(ToolError, match="outside the allowed root"):
        await mcp.call_tool("write_raw_output", {"path": "s.aseprite", "output": "../escape.png"})

    assert not (sandboxed.parent / "escape.png").exists()


async def test_registry_refuses_existing_output_without_overwrite_argument(sandboxed: Path):
    (sandboxed / "taken.png").write_bytes(b"keep")

    with pytest.raises(ToolError, match="already exists"):
        await mcp.call_tool("write_raw_output", {"path": "s.aseprite", "output": "taken.png"})


async def test_registry_refuses_unknown_output_extension(sandboxed: Path):
    with pytest.raises(ToolError, match=r"cannot save out\.xyz"):
        await mcp.call_tool("write_raw_output", {"path": "s.aseprite", "output": "out.xyz"})
