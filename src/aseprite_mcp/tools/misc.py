from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import server
from ..config import Settings
from ..errors import ToolError
from ..guide import GUIDES, Topic
from ..ops import Op, run_ops
from ..paths import resolve_path
from ._registry import READ_ONLY, SpritePath, run_batch

MAX_SCRIPT_BYTES = 200 * 1024


class BatchItem(BaseModel):
    tool: str = Field(description="Name of a batchable tool, e.g. resize_sprite")
    args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments of that tool, without the path"
    )


@server.mcp.tool()
async def batch(
    path: SpritePath,
    ops: Annotated[
        list[BatchItem], Field(min_length=1, description="Tools to run, in order, as {tool, args}")
    ],
) -> list[dict[str, Any]]:
    """Run several single-step tools on one sprite in one go and return their results in order.

    The ops run in a single Aseprite process and are saved once at the end. If any op
    fails, nothing is saved and the error names the failing op. create_sprite and other
    multi-step tools are not accepted. One call takes at most 1000 ops by default. An arg
    a tool does not have is an error here, while a direct call ignores it.

    Example: {"path": "hero.aseprite", "ops": [{"tool": "draw_rect", "args": {"rect":
    {"x": 0, "y": 0, "w": 8, "h": 8}, "color": "#222034", "fill": true}}, {"tool":
    "draw_line", "args": {"points": [{"x": 0, "y": 7}, {"x": 7, "y": 0}], "color": "#fbf236"}}]}
    """
    settings = server.get_settings()
    if len(ops) > settings.max_batch_ops:
        raise ToolError(
            f"Too many ops in one batch: {len(ops)} (limit {settings.max_batch_ops}); "
            "split them over several calls"
        )
    target = resolve_path(path, settings, must_exist=True)
    return await run_batch(target, [(item.tool, item.args) for item in ops])


@server.mcp.tool(annotations=READ_ONLY)
def pixel_art_guide(
    topic: Annotated[Topic, Field(description="Which notes to show")] = "basics",
) -> str:
    """Short practical notes on drawing or animating pixel art with this server's tools.

    Topics: basics, animation, idle, walk, attack, effects.
    """
    return GUIDES[topic]


@server.mcp.prompt(name="pixel_art_guide")
def pixel_art_guide_prompt(topic: Topic = "basics") -> str:
    """Pixel art tips for one topic: basics, animation, idle, walk, attack or effects."""
    return GUIDES[topic]


async def run_lua(
    script: Annotated[str, Field(description="Lua source run inside Aseprite")],
    path: Annotated[
        str | None,
        Field(description="Sprite to open first; relative paths resolve against the root"),
    ] = None,
    save: Annotated[bool, Field(description="Save the sprite when the script succeeds")] = False,
) -> dict[str, Any]:
    """Run a Lua script with Aseprite's scripting API.

    The code is unrestricted: it can read and write any file and start programs
    (io, os.execute). This tool exists only because the server was started with
    ASEPRITE_MCP_ALLOW_LUA=1; use it only in trusted setups.

    With a path, the sprite is open as the global `sprite` (also app.sprite).
    Changes are discarded unless save=true, which saves the sprite once the script
    succeeds. On an error the tool saves nothing (a script that saves the sprite
    itself is outside this guarantee). print() output is returned in `output`
    (up to 64 KB, `truncated` tells if more was cut), and the script's return value
    in `result` (tables become JSON). Relative paths inside the script are not
    resolved against the root. Prefer the dedicated tools when one fits.
    """
    settings = server.get_settings()
    if not settings.allow_lua or settings.sandbox:
        raise ToolError("run_lua is disabled (needs ASEPRITE_MCP_ALLOW_LUA=1 and no sandbox)")
    if len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ToolError(f"The script is too large (limit {MAX_SCRIPT_BYTES // 1024} KB)")
    if save and path is None:
        raise ToolError("save=true needs a path to the sprite to save")
    target = resolve_path(path, settings, must_exist=True) if path is not None else None
    op = Op("run_lua", {"script": script}, mutates=save, label="run_lua")
    [result] = await run_ops(target, [op], settings=settings)
    return {
        "output": result.get("output", ""),
        "truncated": result.get("truncated", False),
        "result": result.get("result"),
        "saved": save,
    }


def add_lua_tool(app: FastMCP, settings: Settings) -> bool:
    """Register run_lua on app when the settings allow it; sandbox mode never does."""
    # These settings decide whether the tool exists; each call checks
    # server.get_settings() again, which is the same object in the real server.
    if not settings.allow_lua or settings.sandbox:
        return False
    app.add_tool(run_lua)
    return True
