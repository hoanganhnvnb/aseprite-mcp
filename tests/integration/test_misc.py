import dataclasses
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from aseprite_mcp import server
from aseprite_mcp.config import Settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.tools.misc import add_lua_tool


@pytest.fixture
def lua(ase_settings: Settings, monkeypatch: pytest.MonkeyPatch):
    settings = dataclasses.replace(ase_settings, allow_lua=True)
    monkeypatch.setattr(server, "get_settings", lambda: settings)
    app = FastMCP("lua-test")
    add_lua_tool(app, settings)

    async def run_lua(**args):
        _, structured = await app.call_tool("run_lua", args)
        return structured

    return run_lua


async def test_run_lua_print_captured(lua):
    result = await lua(script='print("hello", 42, nil)\nprint(true)')

    assert result["output"] == "hello\t42\tnil\ntrue\n"
    assert result["truncated"] is False


async def test_run_lua_returns_value(lua):
    result = await lua(script='return { size = 3, names = { "a", "b" }, ok = true }')

    assert result["result"] == {"size": 3, "names": ["a", "b"], "ok": True}


async def test_run_lua_without_return_gives_null_result(lua):
    result = await lua(script="local x = 1")

    assert result["result"] is None


async def test_run_lua_sees_the_opened_sprite(lua, make_sprite, tmp_path: Path):
    path = await make_sprite(tmp_path, w=5, h=3)

    result = await lua(script="return { sprite.width, sprite.height }", path=path.name)

    assert result["result"] == [5, 3]


async def test_run_lua_error_reported(lua):
    with pytest.raises(ToolError, match=r"run_lua:2: boom"):
        await lua(script='local a = 1\nerror("boom")')


async def test_run_lua_syntax_error_reported(lua):
    with pytest.raises(ToolError, match=r"syntax error: run_lua:1: .*near"):
        await lua(script="return (")


async def test_run_lua_error_shows_output_printed_before_it(lua):
    with pytest.raises(ToolError, match=r"(?s)nil value.*got here"):
        await lua(script='print("got here")\nlocal t = nil\nreturn t.x')


async def test_run_lua_changes_discarded_without_save(lua, make_sprite, pixels, tmp_path: Path):
    path = await make_sprite(tmp_path, w=2, h=2)

    result = await lua(
        script="sprite.cels[1].image:drawPixel(0, 0, app.pixelColor.rgba(255, 0, 0))",
        path=path.name,
    )

    assert result["saved"] is False
    assert await pixels(path, read=[(0, 0)]) == [[0, 0, 0, 0]]


async def test_run_lua_save_persists_changes(lua, make_sprite, pixels, tmp_path: Path):
    path = await make_sprite(tmp_path, w=2, h=2)

    result = await lua(
        script="sprite.cels[1].image:drawPixel(1, 0, app.pixelColor.rgba(255, 0, 0))",
        path=path.name,
        save=True,
    )

    assert result["saved"] is True
    assert await pixels(path, read=[(1, 0)]) == [[255, 0, 0, 255]]


async def test_run_lua_error_leaves_file_untouched(lua, make_sprite, tmp_path: Path):
    path = await make_sprite(tmp_path, w=2, h=2)
    before = path.read_bytes()
    inode = path.stat().st_ino

    with pytest.raises(ToolError, match="half done"):
        await lua(
            script='sprite:resize(8, 8)\nerror("half done")',
            path=path.name,
            save=True,
        )

    assert path.read_bytes() == before
    assert path.stat().st_ino == inode


async def test_run_lua_save_without_path_rejected(lua):
    with pytest.raises(ToolError, match="save=true needs a path"):
        await lua(script="return 1", save=True)


async def test_run_lua_missing_file_rejected(lua):
    with pytest.raises(ToolError, match="File not found"):
        await lua(script="return 1", path="missing.aseprite")


async def test_run_lua_output_truncated_at_limit(lua):
    result = await lua(script='for i = 1, 5000 do print(string.rep("x", 99)) end')

    assert len(result["output"]) == 65536
    assert result["truncated"] is True


async def test_run_lua_unencodable_return_value_becomes_text(lua):
    result = await lua(script="return { f = print, n = 0/0 }")

    assert result["result"]["f"].startswith("function")
    assert result["result"]["n"] in ("nan", "-nan")


async def test_run_lua_cyclic_return_value_rejected(lua):
    with pytest.raises(ToolError, match="refers to itself"):
        await lua(script="local t = {}\nt.self = t\nreturn t")


async def test_run_lua_error_with_table_value(lua):
    with pytest.raises(ToolError, match=r"error value: \{"):
        await lua(script="error({ code = 7 })")


async def test_run_lua_invalid_utf8_in_result_is_replaced(lua):
    result = await lua(script="return string.char(104, 255, 105)")

    assert result["result"] == "h\ufffdi"


async def test_run_lua_invalid_utf8_in_output_is_replaced(lua):
    result = await lua(script='print("\\xff")')

    assert result["output"] == "\ufffd\n"


async def test_run_lua_nul_in_output_is_escaped(lua):
    result = await lua(script='print("a\\0b")\nprint("later")')

    assert result["output"] == "a\\0b\nlater\n"
    assert result["truncated"] is False


async def test_run_lua_nul_in_result_is_escaped(lua):
    result = await lua(script='return "r\\0s"')

    assert result["result"] == "r\\0s"


async def test_run_lua_large_string_result_rejected(lua):
    with pytest.raises(ToolError, match="return value is too large"):
        await lua(script='return string.rep("x", 2 * 1024 * 1024)')


async def test_run_lua_long_error_message_is_cut(lua):
    with pytest.raises(ToolError, match="bytes cut") as caught:
        await lua(script='error(string.rep("y", 20 * 1024 * 1024))')

    assert len(str(caught.value)) < 8192


async def test_run_lua_error_object_with_tostring(lua):
    script = 'error(setmetatable({}, { __tostring = function() return "custom failure" end }))'

    with pytest.raises(ToolError, match="custom failure"):
        await lua(script=script)


async def test_run_lua_traceback_shows_only_script_frames(lua):
    with pytest.raises(ToolError, match=r"run_lua:2: deep") as caught:
        await lua(script='local function inner()\n  error("deep")\nend\ninner()')

    assert "run_lua:4" in str(caught.value)
    assert "xpcall" not in str(caught.value)
    assert "ops/misc.lua" not in str(caught.value)
