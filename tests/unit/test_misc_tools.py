import re
import warnings
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from aseprite_mcp import server
from aseprite_mcp.config import load_settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.guide import GUIDES
from aseprite_mcp.server import INSTRUCTIONS, mcp
from aseprite_mcp.tools.misc import add_lua_tool

TOOL_TOKEN = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")


async def _tool_names(app: FastMCP = mcp) -> set[str]:
    return {tool.name for tool in await app.list_tools()}


async def test_run_lua_not_registered_by_default():
    app = FastMCP("t")

    added = add_lua_tool(app, load_settings({}))

    assert added is False
    assert "run_lua" not in await _tool_names(app)


async def test_run_lua_registered_when_allowed():
    app = FastMCP("t")

    add_lua_tool(app, load_settings({"ASEPRITE_MCP_ALLOW_LUA": "1"}))

    assert "run_lua" in await _tool_names(app)


async def test_run_lua_not_registered_when_sandbox_on():
    app = FastMCP("t")
    settings = load_settings({"ASEPRITE_MCP_ALLOW_LUA": "1", "ASEPRITE_MCP_SANDBOX": "1"})

    add_lua_tool(app, settings)

    assert "run_lua" not in await _tool_names(app)


def test_adding_run_lua_raises_no_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        add_lua_tool(FastMCP("t"), load_settings({"ASEPRITE_MCP_ALLOW_LUA": "1"}))


async def test_run_lua_docstring_says_code_is_unrestricted():
    app = FastMCP("t")
    add_lua_tool(app, load_settings({"ASEPRITE_MCP_ALLOW_LUA": "1"}))

    [tool] = await app.list_tools()

    assert "unrestricted" in tool.description


async def test_run_lua_large_script_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = load_settings({"ASEPRITE_MCP_ROOT": str(tmp_path), "ASEPRITE_MCP_ALLOW_LUA": "1"})
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    app = FastMCP("t")
    add_lua_tool(app, settings)

    with pytest.raises(ToolError, match="script is too large"):
        await app.call_tool("run_lua", {"script": "-" * 300_000})


async def test_batch_rejects_run_lua(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "s.aseprite").write_bytes(b"never opened")
    settings = load_settings({"ASEPRITE_MCP_ROOT": str(tmp_path)})
    monkeypatch.setattr(server, "get_settings", lambda: settings)

    with pytest.raises(ToolError, match="'run_lua' cannot be used in batch"):
        await mcp.call_tool(
            "batch", {"path": "s.aseprite", "ops": [{"tool": "run_lua", "args": {"script": ""}}]}
        )


async def test_instructions_mention_only_existing_tools():
    mentioned = set(TOOL_TOKEN.findall(INSTRUCTIONS))

    assert {"view_sprite", "find_stray_pixels", "check_animation"} <= mentioned
    assert mentioned <= await _tool_names()


def test_instructions_are_short():
    assert len(INSTRUCTIONS.strip().splitlines()) <= 25


async def test_every_guide_mentions_only_existing_tools():
    names = await _tool_names()

    for topic, text in GUIDES.items():
        mentioned = set(TOOL_TOKEN.findall(text))
        assert mentioned, topic
        assert mentioned <= names, topic


async def test_pixel_art_guide_returns_text_for_every_topic():
    for topic in ("basics", "animation", "idle", "walk", "attack", "effects"):
        content, _ = await mcp.call_tool("pixel_art_guide", {"topic": topic})

        assert content[0].text == GUIDES[topic]


async def test_pixel_art_guide_defaults_to_basics():
    content, _ = await mcp.call_tool("pixel_art_guide", {})

    assert content[0].text == GUIDES["basics"]


async def test_pixel_art_guide_rejects_unknown_topic():
    with pytest.raises(ToolError, match="topic"):
        await mcp.call_tool("pixel_art_guide", {"topic": "dragons"})


async def test_pixel_art_guide_prompt_registered():
    [prompt] = [p for p in await mcp.list_prompts() if p.name == "pixel_art_guide"]
    rendered = await mcp.get_prompt("pixel_art_guide", {"topic": "walk"})

    assert [arg.name for arg in prompt.arguments] == ["topic"]
    assert rendered.messages[0].content.text == GUIDES["walk"]


async def test_every_tool_has_a_description():
    missing = [tool.name for tool in await mcp.list_tools() if not (tool.description or "").strip()]

    assert missing == []
