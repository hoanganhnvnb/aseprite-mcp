import pytest

from aseprite_mcp.server import mcp
from aseprite_mcp.tools._registry import BATCH_HINT, BATCHABLE, op_tool
from helpers import DOC_EXAMPLE_TOOLS, doc_example

# The longest description is about 1150 characters; clients load all of them up front.
MAX_DESCRIPTION = 1400

HINTED = {
    "draw_pixels",
    "draw_line",
    "draw_rect",
    "draw_ellipse",
    "draw_polygon",
    "fill_area",
    "draw_gradient",
    "fill_pattern",
    "draw_ascii",
    "draw_isometric_box",
    "draw_text",
    "draw_tile",
    "set_tiles",
    "move_region",
    "erase_region",
}


async def descriptions() -> dict[str, str]:
    return {tool.name: tool.description or "" for tool in await mcp.list_tools()}


async def test_tool_descriptions_stay_within_budget():
    too_long = {
        name: len(d) for name, d in (await descriptions()).items() if len(d) > MAX_DESCRIPTION
    }

    assert too_long == {}


async def test_batch_hint_is_on_exactly_the_drawing_tools():
    hinted = {name for name, d in (await descriptions()).items() if BATCH_HINT in d}

    assert hinted == HINTED


def test_hinted_tools_are_batchable_mutations():
    assert all(BATCHABLE[name][1] for name in HINTED)


def test_batch_hint_refused_on_read_only_tool():
    with pytest.raises(TypeError, match="only for mutating tools"):

        @op_tool("sprite_info", mutates=False, batch_hint=True)
        def peek() -> dict:
            """Never registered."""
            return {}


@pytest.mark.parametrize("name", DOC_EXAMPLE_TOOLS)
async def test_example_uses_real_parameters(name: str):
    tool = {tool.name: tool for tool in await mcp.list_tools()}[name]

    args = doc_example(tool.description or "")

    assert set(args) <= set(tool.inputSchema["properties"])
    assert set(tool.inputSchema["required"]) <= set(args)
