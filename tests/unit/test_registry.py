import inspect
import warnings
from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import Field

from aseprite_mcp import __version__, server
from aseprite_mcp.config import load_settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.server import mcp
from aseprite_mcp.tools._registry import BATCHABLE, _args_model, op_tool


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
def write_raw_output(output: Annotated[str, Field(description="File to write")]) -> dict[str, Any]:
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


def test_layer_tools_are_batchable_mutations():
    for name in ("add_layer", "update_layer", "delete_layer", "duplicate_layer"):
        assert BATCHABLE[name][:2] == (name, True)
    assert BATCHABLE["merge_layer_down"][:2] == ("merge_layer_down", True)
    assert BATCHABLE["flatten_sprite"][:2] == ("flatten_sprite", True)


async def test_add_layer_schema():
    schema = await _schema("add_layer")

    assert schema["required"] == ["path", "name"]
    assert schema["properties"]["kind"]["enum"] == ["normal", "group", "tilemap"]
    assert schema["properties"]["parent"]["default"] == ""


async def test_update_layer_schema():
    schema = await _schema("update_layer")

    assert schema["required"] == ["path", "layer"]
    blend = schema["properties"]["blend_mode"]["anyOf"][0]
    assert blend["enum"][:3] == ["normal", "multiply", "screen"]
    assert len(blend["enum"]) == 19
    opacity = schema["properties"]["opacity"]["anyOf"][0]
    assert (opacity["minimum"], opacity["maximum"]) == (0, 255)


async def test_single_layer_tools_require_only_the_layer():
    for name in ("delete_layer", "duplicate_layer", "merge_layer_down"):
        assert (await _schema(name))["required"] == ["path", "layer"]
    assert (await _schema("flatten_sprite"))["required"] == ["path"]


async def test_frame_spec_schema_accepts_string_or_integer():
    frames = (await _schema("delete_frames"))["properties"]["frames"]

    assert [item["type"] for item in frames["anyOf"]] == ["string", "integer"]


def test_frame_tools_are_batchable():
    assert BATCHABLE["copy_frames"][:2] == ("copy_frames", True)
    assert BATCHABLE["set_tag"][:2] == ("set_tag", True)


def test_cel_tools_are_batchable_mutations():
    for name in ("set_cel", "clear_cels", "tween_cels", "oscillate_cels"):
        assert BATCHABLE[name][:2] == (name, True)


async def test_set_cel_schema():
    schema = await _schema("set_cel")

    assert schema["required"] == ["path", "layer", "frames"]
    opacity = schema["properties"]["opacity"]["anyOf"][0]
    assert (opacity["minimum"], opacity["maximum"]) == (0, 255)
    assert schema["properties"]["create"]["default"] is False


async def test_clear_cels_schema():
    assert (await _schema("clear_cels"))["required"] == ["path", "layer", "frames"]


async def test_tween_cels_schema():
    schema = await _schema("tween_cels")

    assert schema["required"] == ["path", "layer", "frames", "property", "start", "end"]
    assert schema["properties"]["property"]["enum"] == ["position", "opacity", "scale"]
    assert schema["properties"]["easing"]["enum"] == [
        "linear",
        "ease_in",
        "ease_out",
        "ease_in_out",
        "ease_out_back",
        "bounce",
    ]
    assert schema["properties"]["anchor"]["default"] == "center"
    assert "XY" in schema["$defs"]


async def test_oscillate_cels_schema():
    schema = await _schema("oscillate_cels")

    assert schema["required"] == ["path", "layer", "frames"]
    cycles = schema["properties"]["cycles"]
    assert (cycles["minimum"], cycles["maximum"], cycles["default"]) == (0.1, 64, 1.0)


def test_draw_tools_are_batchable_mutations():
    for name in ("draw_pixels", "draw_line", "draw_rect", "draw_ellipse", "draw_polygon"):
        assert BATCHABLE[name][:2] == (name, True)
    assert BATCHABLE["fill_area"][:2] == ("fill_area", True)


async def test_draw_tools_required_params():
    required = {
        "draw_pixels": ["path", "pixels"],
        "draw_line": ["path", "points", "color"],
        "draw_rect": ["path", "rect", "color"],
        "draw_ellipse": ["path", "cx", "cy", "rx", "ry", "color"],
        "draw_polygon": ["path", "points", "color"],
        "fill_area": ["path", "x", "y", "color"],
    }
    for name, params in required.items():
        assert (await _schema(name))["required"] == params


async def test_draw_tools_share_target_params():
    for name in ("draw_pixels", "draw_line", "draw_rect", "fill_area"):
        props = (await _schema(name))["properties"]
        assert (props["layer"]["default"], props["frame"]["default"]) == ("", 1)
        assert props["create_cel"]["default"] is True


async def test_draw_pixels_schema_limits_pixel_count():
    schema = await _schema("draw_pixels")

    assert schema["properties"]["pixels"]["maxItems"] == 16384
    assert "Pixel" in schema["$defs"]


async def test_draw_line_schema():
    props = (await _schema("draw_line"))["properties"]

    assert props["points"]["minItems"] == 2
    assert (props["thickness"]["minimum"], props["thickness"]["maximum"]) == (1, 64)
    assert props["blend"]["default"] is False


async def test_fill_area_schema_has_no_blend():
    props = (await _schema("fill_area"))["properties"]

    assert "blend" not in props
    assert (props["tolerance"]["minimum"], props["tolerance"]["maximum"]) == (0, 255)


def test_gradient_pattern_ascii_and_box_are_batchable_edits():
    assert BATCHABLE["draw_gradient"][:2] == ("draw_gradient", True)
    assert BATCHABLE["fill_pattern"][:2] == ("fill_pattern", True)
    assert BATCHABLE["draw_ascii"][:2] == ("draw_runs", True)
    assert BATCHABLE["draw_isometric_box"][:2] == ("draw_runs", True)


async def test_gradient_pattern_ascii_and_box_required_params():
    required = {
        "draw_gradient": ["path", "rect", "colors"],
        "fill_pattern": ["path", "rect", "color_a", "color_b", "density"],
        "draw_ascii": ["path", "x", "y", "rows", "legend"],
        "draw_isometric_box": ["path", "x", "y", "w", "d", "h", "top", "left", "right"],
    }
    for name, params in required.items():
        schema = await _schema(name)
        assert schema["required"] == params
        assert schema["properties"]["blend"]["default"] is False


async def test_draw_gradient_schema():
    props = (await _schema("draw_gradient"))["properties"]

    assert (props["colors"]["minItems"], props["colors"]["maxItems"]) == (2, 16)
    assert props["direction"]["enum"] == ["horizontal", "vertical"]
    assert props["dither"]["enum"] == ["none", "bayer2", "bayer4", "bayer8"]
    assert props["dither"]["default"] == "none"


async def test_fill_pattern_schema():
    props = (await _schema("fill_pattern"))["properties"]

    assert (props["density"]["minimum"], props["density"]["maximum"]) == (0, 1)
    assert props["matrix"]["enum"] == ["bayer2", "bayer4", "bayer8"]
    assert props["matrix"]["default"] == "bayer4"


async def test_draw_ascii_schema():
    props = (await _schema("draw_ascii"))["properties"]

    assert (props["rows"]["minItems"], props["rows"]["maxItems"]) == (1, 256)
    assert props["rows"]["items"]["maxLength"] == 256
    assert props["outline"]["default"] is None


async def test_draw_isometric_box_schema():
    props = (await _schema("draw_isometric_box"))["properties"]

    assert (props["w"]["minimum"], props["w"]["maximum"]) == (1, 128)
    assert (props["d"]["minimum"], props["d"]["maximum"]) == (1, 128)
    assert (props["h"]["minimum"], props["h"]["maximum"]) == (0, 256)
    assert "z" not in props


def test_region_tools_are_batchable_mutations():
    for name in ("move_region", "erase_region", "flip", "rotate"):
        assert BATCHABLE[name][:2] == (name, True)


async def test_region_tools_required_params():
    required = {
        "move_region": ["path", "layer", "rect", "dx", "dy"],
        "erase_region": ["path", "layer", "rect"],
        "flip": ["path", "axis"],
        "rotate": ["path", "angle"],
    }
    for name, params in required.items():
        assert (await _schema(name))["required"] == params


async def test_move_region_schema():
    props = (await _schema("move_region"))["properties"]

    assert props["copy"]["default"] is False
    assert props["blend"]["default"] is False
    assert props["frame"]["default"] == 1
    assert props["target_layer"]["default"] is None


async def test_flip_and_rotate_schema():
    flip = (await _schema("flip"))["properties"]
    rotate = (await _schema("rotate"))["properties"]

    assert flip["axis"]["enum"] == ["horizontal", "vertical"]
    assert rotate["angle"]["enum"] == [90, 180, 270]
    assert flip["frames"]["default"] == rotate["frames"]["default"] == "all"
    assert flip["layer"]["default"] is rotate["layer"]["default"] is None


def test_no_userwarning_for_copy_parameter():
    builder = BATCHABLE["move_region"][2]

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = _args_model("move_region", inspect.signature(builder, eval_str=True))
        args = model.model_validate(
            {"layer": "L", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}, "dx": 1, "dy": 0, "copy": True}
        )

    assert args.copy is True


def test_quality_slice_and_tilemap_tools_are_batchable():
    for name in ("check_animation", "list_slices", "get_tilemap_info"):
        assert BATCHABLE[name][:2] == (name, False)
    for name in ("repair_animation", "copy_layers", "create_slice", "set_tiles", "draw_tile"):
        assert BATCHABLE[name][:2] == (name, True)


async def test_copy_layers_takes_target_and_source_paths():
    schema = await _schema("copy_layers")

    assert list(schema["properties"])[:2] == ["target", "source"]
    assert set(schema["required"]) == {"target", "source", "layers"}


async def test_copy_layers_refuses_source_outside_sandbox(sandboxed: Path):
    with pytest.raises(ToolError, match="outside the allowed root"):
        await mcp.call_tool(
            "copy_layers", {"target": "s.aseprite", "source": "../other.aseprite", "layers": ["A"]}
        )


async def test_batch_copy_layers_refuses_source_equal_to_batch_sprite(sandboxed: Path):
    with pytest.raises(ToolError, match="op 1 \\(copy_layers\\): source must be a different file"):
        await mcp.call_tool(
            "batch",
            {
                "path": "s.aseprite",
                "ops": [{"tool": "copy_layers", "args": {"source": "s.aseprite", "layers": ["A"]}}],
            },
        )


async def test_set_tiles_schema_limits_cells():
    tiles = (await _schema("set_tiles"))["properties"]["tiles"]

    assert tiles["maxItems"] == 4096


async def test_save_copy_refuses_output_equal_to_sprite(sandboxed: Path):
    with pytest.raises(ToolError, match="output must be a different file than the sprite"):
        await mcp.call_tool(
            "save_copy", {"path": "s.aseprite", "output": "./s.aseprite", "overwrite": True}
        )


async def test_every_tool_parameter_has_a_description():
    missing = [
        f"{tool.name}.{name}"
        for tool in await mcp.list_tools()
        for name, prop in tool.inputSchema["properties"].items()
        if not prop.get("description")
    ]

    assert missing == []


async def test_read_only_tools_are_marked():
    annotations = {tool.name: tool.annotations for tool in await mcp.list_tools()}

    assert annotations["get_sprite_info"].readOnlyHint is True
    assert annotations["view_sprite"].readOnlyHint is True
    assert annotations["draw_rect"] is None
    assert annotations["save_copy"] is None


def test_server_reports_package_version():
    options = mcp._mcp_server.create_initialization_options()

    assert options.server_version == __version__


async def test_direct_call_with_bad_arguments_gives_short_message():
    with pytest.raises(ToolError) as info:
        await mcp.call_tool(
            "draw_rect",
            {"path": "a.aseprite", "rect": {"x": 0, "y": 0, "w": 0, "h": 1}, "color": "red"},
        )

    message = str(info.value)
    assert message.startswith("draw_rect: invalid arguments: rect.w: ")
    assert "Invalid color 'red'" in message
    assert "errors.pydantic.dev" not in message
