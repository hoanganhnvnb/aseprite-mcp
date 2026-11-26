from pathlib import Path

import pytest

from aseprite_mcp import server
from aseprite_mcp.server import mcp
from helpers import DOC_EXAMPLE_TOOLS, doc_example


@pytest.mark.parametrize("name", DOC_EXAMPLE_TOOLS)
async def test_description_example_runs(
    name, ase_settings, make_sprite, monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(server, "get_settings", lambda: ase_settings)
    await make_sprite(tmp_path, 16, 16, name="hero.aseprite")
    tool = {tool.name: tool for tool in await mcp.list_tools()}[name]

    content, _ = await mcp.call_tool(name, doc_example(tool.description or ""))

    assert content


@pytest.mark.parametrize("name", ["draw_pixels", "draw_rect", "draw_ascii", "draw_text"])
async def test_drawing_example_paints_something(
    name, ase_settings, make_sprite, monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(server, "get_settings", lambda: ase_settings)
    await make_sprite(tmp_path, 16, 16, name="hero.aseprite")
    tool = {tool.name: tool for tool in await mcp.list_tools()}[name]

    _, result = await mcp.call_tool(name, doc_example(tool.description or ""))

    assert result["painted"] > 0
