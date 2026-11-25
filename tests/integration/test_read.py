import base64
import dataclasses
import io
from pathlib import Path

import pytest
from mcp.types import ImageContent, TextContent
from PIL import Image

from aseprite_mcp import ops, server
from aseprite_mcp.errors import ToolError
from aseprite_mcp.tools import read

RED = "#ff0000"
BLUE = "#0000ff"


async def new_sprite(call, w: int = 4, h: int = 4, **args) -> None:
    await call("create_sprite", path="a.aseprite", width=w, height=h, **args)


async def put(call, *pixels: tuple[int, int, str], **args) -> None:
    await call(
        "draw_pixels",
        path="a.aseprite",
        pixels=[{"x": x, "y": y, "color": c} for x, y, c in pixels],
        **args,
    )


def rect(x: int, y: int, w: int, h: int) -> dict:
    return {"x": x, "y": y, "w": w, "h": h}


async def view(**args) -> tuple[str, Image.Image]:
    note, png = await server.mcp.call_tool("view_sprite", {"path": "a.aseprite", **args})
    assert isinstance(note, TextContent)
    assert isinstance(png, ImageContent)
    assert png.mimeType == "image/png"
    return note.text, Image.open(io.BytesIO(base64.b64decode(png.data)))


@pytest.fixture
def processes(monkeypatch: pytest.MonkeyPatch) -> list:
    started = []
    real = ops.run_script

    async def counting(*args, **kwargs):
        started.append(args[0])
        return await real(*args, **kwargs)

    monkeypatch.setattr(ops, "run_script", counting)
    return started


async def test_read_pixels_rows_with_legend(call):
    await new_sprite(call, 3, 2)
    await put(call, (0, 0, RED), (2, 1, BLUE))

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 3, 2))

    assert result == {
        "x": 0,
        "y": 0,
        "w": 3,
        "h": 2,
        "rows": ["A..", "..B"],
        "legend": {"A": "#ff0000", "B": "#0000ff"},
    }


async def test_read_pixels_hex_rows(call):
    await new_sprite(call, 3, 2)
    await put(call, (0, 0, RED), (2, 1, "#00ff0080"))

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 3, 2), format="hex")

    assert result["rows"] == ["#ff0000 . .", ". . #00ff0080"]


async def test_read_pixels_json_rows(call):
    await new_sprite(call, 2, 1)
    await put(call, (1, 0, BLUE))

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1), format="json")

    assert result == {"x": 0, "y": 0, "w": 2, "h": 1, "pixels": [["transparent", "#0000ff"]]}


async def test_read_pixels_rect_partly_outside_canvas(call):
    await new_sprite(call, 2, 2)
    await put(call, (1, 1, RED))

    result = await call("read_pixels", path="a.aseprite", rect=rect(1, 1, 2, 2))

    assert result["rows"] == ["A.", ".."]


async def test_read_pixels_rect_outside_canvas_fails(call):
    await new_sprite(call, 2, 2)

    with pytest.raises(ToolError, match="outside the canvas"):
        await call("read_pixels", path="a.aseprite", rect=rect(5, 5, 2, 2))


async def test_read_pixels_over_limit(call, processes):
    await new_sprite(call, 4, 4)
    processes.clear()

    with pytest.raises(ToolError, match="65536.*view_sprite"):
        await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 257, 256))

    assert processes == []


async def test_read_pixels_limit_counts_the_requested_rect(call, ase_settings, monkeypatch):
    await new_sprite(call, 4, 4)
    small = dataclasses.replace(ase_settings, max_read_pixels=6)
    monkeypatch.setattr(server, "get_settings", lambda: small)

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 3, 2))
    assert result["rows"] == ["...", "..."]

    with pytest.raises(ToolError, match="7 pixels"):
        await call("read_pixels", path="a.aseprite", rect=rect(-3, 0, 7, 1))


async def test_read_ascii_matches_draw_ascii(call, tmp_path: Path):
    rows = ["..#..", ".#o#.", "#o+o#", ".#o#."]
    legend = {"#": "#203040", "o": "#ff8800", "+": "#ffffff80"}
    await new_sprite(call, 6, 5)
    await call("draw_ascii", path="a.aseprite", x=1, y=1, rows=rows, legend=legend)

    read = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 6, 5))
    await call("create_sprite", path="b.aseprite", width=6, height=5)
    await call("draw_ascii", path="b.aseprite", x=0, y=0, rows=read["rows"], legend=read["legend"])

    copy = await call("read_pixels", path="b.aseprite", rect=rect(0, 0, 6, 5), format="json")
    original = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 6, 5), format="json")
    assert copy["pixels"] == original["pixels"]
    assert original["pixels"][3][3] == "#ffffff80"


async def test_composite_ignores_hidden_layer(call):
    await new_sprite(call, 2, 1)
    await put(call, (0, 0, RED))
    await call("add_layer", path="a.aseprite", name="hidden")
    await put(call, (1, 0, BLUE), layer="hidden")
    await call("update_layer", path="a.aseprite", layer="hidden", visible=False)

    pixels = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1))
    stats = await call("get_color_stats", path="a.aseprite")

    assert pixels["rows"] == ["A."]
    assert [c["color"] for c in stats["colors"]] == ["#ff0000"]


async def test_composite_ignores_layer_inside_hidden_group(call):
    await new_sprite(call, 2, 1)
    await call("add_layer", path="a.aseprite", name="g", kind="group")
    await call("add_layer", path="a.aseprite", name="inner", parent="g")
    await put(call, (1, 0, BLUE), layer="inner")
    await call("update_layer", path="a.aseprite", layer="g", visible=False)

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1))

    assert result["rows"] == [".."]


async def test_read_pixels_named_layer_leaves_out_the_others(call):
    await new_sprite(call, 2, 1)
    await put(call, (0, 0, RED))
    await call("add_layer", path="a.aseprite", name="top")
    await put(call, (1, 0, BLUE), layer="top")

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1), layer="top")

    assert result["rows"] == [".A"]
    assert result["legend"] == {"A": "#0000ff"}


async def test_read_pixels_named_layer_ignores_layer_opacity_and_visibility(call):
    await new_sprite(call, 1, 1)
    await put(call, (0, 0, RED))
    await call("update_layer", path="a.aseprite", layer="Layer 1", visible=False, opacity=64)

    result = await call(
        "read_pixels", path="a.aseprite", rect=rect(0, 0, 1, 1), layer="Layer 1", format="json"
    )

    assert result["pixels"] == [["#ff0000"]]


async def test_composite_applies_layer_opacity(call):
    await new_sprite(call, 1, 1)
    await put(call, (0, 0, RED))
    await call("update_layer", path="a.aseprite", layer="Layer 1", opacity=128)

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 1, 1), format="json")

    assert result["pixels"] == [["#ff000080"]]


async def test_read_pixels_layer_cel_with_negative_offset(call):
    await new_sprite(call, 3, 1)
    await put(call, (0, 0, RED), (1, 0, BLUE))
    await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, x=-1, y=0)

    result = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 3, 1), layer="Layer 1")

    assert result["rows"] == ["A.."]
    assert result["legend"] == {"A": "#0000ff"}


async def test_read_pixels_refuses_a_group(call):
    await new_sprite(call, 2, 1)
    await call("add_layer", path="a.aseprite", name="g", kind="group")

    with pytest.raises(ToolError, match="'g' is a group"):
        await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1), layer="g")


async def test_read_pixels_indexed_sprite_gives_palette_colours(call):
    await new_sprite(call, 2, 1, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["transparent", RED, BLUE])
    await put(call, (0, 0, BLUE))

    composite = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1))
    layer = await call(
        "read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 1), layer="Layer 1", format="hex"
    )

    assert composite["rows"] == ["A."]
    assert composite["legend"] == {"A": "#0000ff"}
    assert layer["rows"] == ["#0000ff ."]


async def test_read_pixels_indexed_background_shows_index_zero_opaque(call, pixels, tmp_path):
    await new_sprite(call, 1, 1, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["#102030", RED])
    await pixels(tmp_path / "a.aseprite", background=True)

    layer = await call(
        "read_pixels", path="a.aseprite", rect=rect(0, 0, 1, 1), layer="Background", format="hex"
    )
    composite = await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 1, 1), format="hex")

    assert layer["rows"] == ["#102030"]
    assert composite["rows"] == ["#102030"]


async def test_read_pixels_grayscale_sprite(call):
    await new_sprite(call, 1, 1, color_mode="grayscale")
    await put(call, (0, 0, "#646464"))

    result = await call(
        "read_pixels", path="a.aseprite", rect=rect(0, 0, 1, 1), layer="Layer 1", format="hex"
    )

    assert result["rows"] == ["#646464"]


async def test_read_pixels_frame_out_of_range(call):
    await new_sprite(call, 2, 2)

    with pytest.raises(ToolError, match="frame 3 is out of range"):
        await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 2, 2), frame=3)


async def test_read_tools_do_not_save(call, tmp_path: Path):
    await new_sprite(call, 4, 4)
    await put(call, (1, 1, RED))
    before = (tmp_path / "a.aseprite").read_bytes()

    await call("read_pixels", path="a.aseprite", rect=rect(0, 0, 4, 4))
    await call("get_bounds", path="a.aseprite")
    await call("compare_frames", path="a.aseprite", frame_a=1, frame_b=1)
    await call("get_color_stats", path="a.aseprite")
    await call("find_stray_pixels", path="a.aseprite")
    await view()

    assert (tmp_path / "a.aseprite").read_bytes() == before


async def test_view_sprite_returns_png_under_cap(call):
    await new_sprite(call, 600, 10)

    note, image = await view(scale=8)

    assert image.size == (1800, 30)
    assert "reduced to 3" in note


async def test_view_sprite_default_scale_fits_512(call):
    await new_sprite(call, 16, 8)

    note, image = await view()

    assert image.size == (512, 256)
    assert "scale 32" in note


async def test_view_sprite_shrinks_when_scale_one_is_too_big(call):
    await new_sprite(call, 4096, 16)

    note, image = await view()

    assert image.size == (2048, 8)
    assert "1/2" in note


async def test_view_sprite_many_frames_one_process(call, processes):
    await new_sprite(call, 4, 4)
    await call("add_frames", path="a.aseprite", count=5)
    processes.clear()

    note, image = await view(frames="all")

    assert len(processes) == 1
    # 3 columns and 2 rows of 4x4 frames at scale 32, 4 px apart
    assert image.size == (3 * 128 + 2 * 4, 2 * 128 + 4)
    assert "1-6" in note


async def test_view_sprite_too_many_frames(call):
    await new_sprite(call, 2, 2)
    await call("add_frames", path="a.aseprite", count=64)

    with pytest.raises(ToolError, match="65 frames.*at most 64"):
        await view(frames="all")


async def test_view_sprite_frame_out_of_range(call):
    await new_sprite(call, 2, 2)

    with pytest.raises(ToolError, match="frame 2 is out of range"):
        await view(frames="1-2")


async def test_view_sprite_region_crops(call):
    await new_sprite(call, 8, 8)
    await put(call, (3, 3, RED))

    _, image = await view(region=rect(3, 3, 2, 2), scale=1)

    assert image.size == (2, 2)
    assert image.convert("RGBA").getpixel((0, 0)) == (255, 0, 0, 255)


async def test_view_sprite_layer_shows_only_that_layer(call):
    await new_sprite(call, 2, 1)
    await put(call, (0, 0, RED))
    await call("add_layer", path="a.aseprite", name="top")
    await put(call, (1, 0, BLUE), layer="top")

    _, image = await view(layer="top", scale=1)

    assert image.convert("RGBA").getpixel((1, 0)) == (0, 0, 255, 255)
    assert image.convert("RGBA").getpixel((0, 0)) != (255, 0, 0, 255)


async def test_view_sprite_grid_changes_the_image(call):
    await new_sprite(call, 4, 4, background="#ffffff")

    _, plain = await view(scale=8)
    note, gridded = await view(scale=8, grid=True)

    assert plain.size == gridded.size
    assert plain.convert("RGBA").getpixel((8, 4)) == (255, 255, 255, 255)
    assert gridded.convert("RGBA").getpixel((8, 4)) != (255, 255, 255, 255)
    assert "grid" not in note


async def test_view_sprite_grid_skipped_below_scale_4(call):
    await new_sprite(call, 4, 4)

    note, _ = await view(scale=2, grid=True)

    assert "grid needs scale 4" in note


async def test_view_sprite_rulers_add_margins(call):
    await new_sprite(call, 4, 4)

    _, plain = await view(scale=8)
    _, ruled = await view(scale=8, rulers=True)

    assert ruled.width > plain.width
    assert ruled.height > plain.height


async def test_view_sprite_onion_skin_shows_previous_frame(call):
    await new_sprite(call, 2, 1)
    await call("add_frames", path="a.aseprite")
    await put(call, (0, 0, RED))
    await put(call, (1, 0, BLUE), frame=2)

    _, plain = await view(frames="2", scale=1)
    note, onion = await view(frames="2", scale=1, onion_skin=1)

    r, g, b, _ = onion.convert("RGBA").getpixel((0, 0))
    assert onion.convert("RGBA").getpixel((0, 0)) != plain.convert("RGBA").getpixel((0, 0))
    assert r > g and r > b
    assert onion.convert("RGBA").getpixel((1, 0)) == (0, 0, 255, 255)
    assert "Onion skin" in note


async def test_view_sprite_cleans_up_its_files(call, tmp_path: Path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.setattr("tempfile.tempdir", None)
    await new_sprite(call, 4, 4)

    await view(frames="1")
    with pytest.raises(ToolError):
        await view(frames="3")

    assert list(scratch.iterdir()) == []


async def test_view_sprite_cannot_be_batched(call):
    await new_sprite(call, 2, 2)

    with pytest.raises(ToolError, match="'view_sprite' cannot be used in batch"):
        await call("batch", path="a.aseprite", ops=[{"tool": "view_sprite", "args": {}}])


async def test_compare_frames_bbox(call):
    await new_sprite(call, 6, 6)
    await call("add_frames", path="a.aseprite", copy_content=True)
    await put(call, (1, 1, RED), (3, 2, BLUE), frame=2)

    result = await call("compare_frames", path="a.aseprite", frame_a=1, frame_b=2)

    assert result == {
        "frame_a": 1,
        "frame_b": 2,
        "identical": False,
        "different_pixels": 2,
        "bounds": {"x": 1, "y": 1, "w": 3, "h": 2},
        "area": {"x": 0, "y": 0, "w": 6, "h": 6},
    }


async def test_compare_frames_identical(call):
    await new_sprite(call, 4, 4)
    await put(call, (1, 1, RED))
    await call("add_frames", path="a.aseprite", copy_content=True)

    result = await call("compare_frames", path="a.aseprite", frame_a=1, frame_b=2)

    assert result["identical"] is True
    assert result["different_pixels"] == 0
    assert result["bounds"] is None


async def test_compare_frames_region_limits_the_check(call):
    await new_sprite(call, 6, 6)
    await call("add_frames", path="a.aseprite")
    await put(call, (0, 0, RED), (4, 4, RED), frame=2)

    result = await call(
        "compare_frames", path="a.aseprite", frame_a=1, frame_b=2, region=rect(3, 3, 3, 3)
    )

    assert result["different_pixels"] == 1
    assert result["bounds"] == {"x": 4, "y": 4, "w": 1, "h": 1}


async def test_compare_frames_on_one_layer(call):
    await new_sprite(call, 4, 4)
    await call("add_layer", path="a.aseprite", name="top")
    await call("add_frames", path="a.aseprite")
    await put(call, (2, 2, RED), frame=2)

    result = await call("compare_frames", path="a.aseprite", frame_a=1, frame_b=2, layer="top")

    assert result["identical"] is True


async def test_compare_frames_ignores_rgb_of_transparent_pixels(call, pixels, tmp_path):
    await new_sprite(call, 2, 1)
    await call("add_frames", path="a.aseprite")
    await pixels(tmp_path / "a.aseprite", put=[(0, 0, 255, 0, 0, 0)], frame=2)

    result = await call("compare_frames", path="a.aseprite", frame_a=1, frame_b=2, layer="Layer 1")

    assert result["identical"] is True


async def test_get_bounds_per_frame_and_overall(call):
    await new_sprite(call, 8, 8)
    await call("add_frames", path="a.aseprite", count=2)
    await put(call, (1, 2, RED), (3, 2, RED))
    await put(call, (6, 7, BLUE), frame=3)

    result = await call("get_bounds", path="a.aseprite")

    assert result == {
        "frames": [
            {"frame": 1, "bounds": {"x": 1, "y": 2, "w": 3, "h": 1}},
            {"frame": 2, "bounds": None},
            {"frame": 3, "bounds": {"x": 6, "y": 7, "w": 1, "h": 1}},
        ],
        "bounds": {"x": 1, "y": 2, "w": 6, "h": 6},
    }


async def test_get_bounds_over_many_frames(call):
    await new_sprite(call, 256, 256)
    await call("add_frames", path="a.aseprite", count=63)
    await put(call, (10, 20, RED))
    await put(call, (200, 100, RED), frame=64)

    result = await call("get_bounds", path="a.aseprite")

    assert len(result["frames"]) == 64
    assert result["frames"][1] == {"frame": 2, "bounds": None}
    assert result["frames"][63] == {"frame": 64, "bounds": {"x": 200, "y": 100, "w": 1, "h": 1}}
    assert result["bounds"] == {"x": 10, "y": 20, "w": 191, "h": 81}


async def test_get_bounds_of_a_layer_frame_without_a_cel(call):
    await new_sprite(call, 4, 4)
    await call("add_frames", path="a.aseprite")
    await put(call, (1, 1, RED))

    result = await call("get_bounds", path="a.aseprite", layer="Layer 1")

    assert result["frames"][1] == {"frame": 2, "bounds": None}


async def test_get_bounds_empty_sprite(call):
    await new_sprite(call, 4, 4)

    result = await call("get_bounds", path="a.aseprite", frames="1")

    assert result == {"frames": [{"frame": 1, "bounds": None}], "bounds": None}


async def test_get_bounds_of_a_layer_clips_to_the_canvas(call):
    await new_sprite(call, 4, 4)
    await put(call, (0, 0, RED), (2, 1, RED))
    await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, x=-1, y=0)

    result = await call("get_bounds", path="a.aseprite", layer="Layer 1")

    assert result["bounds"] == {"x": 1, "y": 1, "w": 1, "h": 1}


async def test_get_color_stats_counts_colours(call):
    await new_sprite(call, 2, 2)
    await put(call, (0, 0, RED), (1, 0, RED), (0, 1, RED), (1, 1, BLUE))

    result = await call("get_color_stats", path="a.aseprite")

    assert result == {
        "frame": 1,
        "pixels": 4,
        "transparent": 0,
        "unique": 2,
        "colors": [
            {"color": "#ff0000", "count": 3, "percent": 75.0},
            {"color": "#0000ff", "count": 1, "percent": 25.0},
        ],
    }


async def test_get_color_stats_keeps_alpha_apart(call):
    await new_sprite(call, 3, 1)
    await put(call, (0, 0, RED), (1, 0, "#ff000080"))

    result = await call("get_color_stats", path="a.aseprite")

    assert result["transparent"] == 1
    assert result["colors"] == [
        {"color": "#ff000080", "count": 1, "percent": 50.0},
        {"color": "#ff0000", "count": 1, "percent": 50.0},
    ]


async def test_get_color_stats_top_limits_the_list(call):
    await new_sprite(call, 3, 1)
    await put(call, (0, 0, RED), (1, 0, BLUE), (2, 0, BLUE))

    result = await call("get_color_stats", path="a.aseprite", top=1)

    assert result["unique"] == 2
    assert result["colors"] == [{"color": "#0000ff", "count": 2, "percent": 66.6667}]


async def test_get_color_stats_rare_colour_is_not_rounded_away(call):
    await new_sprite(call, 200, 200, background="#ffffff")
    await put(call, (0, 0, RED))

    result = await call("get_color_stats", path="a.aseprite")

    assert result["colors"][1] == {"color": "#ff0000", "count": 1, "percent": 0.0025}


async def test_get_color_stats_refuses_too_many_colours(call, monkeypatch):
    monkeypatch.setattr(read, "MAX_STAT_COLORS", 2)
    await new_sprite(call, 3, 1)
    await put(call, (0, 0, RED), (1, 0, BLUE), (2, 0, "#00ff00"))

    with pytest.raises(ToolError, match="more than 2 different colours"):
        await call("get_color_stats", path="a.aseprite")


async def test_lint_detects_lone_pixel(call):
    await new_sprite(call, 8, 8)
    await call("draw_rect", path="a.aseprite", rect=rect(0, 0, 3, 3), color=RED, fill=True)
    await put(call, (6, 6, BLUE))

    result = await call("find_stray_pixels", path="a.aseprite")

    assert result["lone_pixels"] == [{"x": 6, "y": 6, "color": "#0000ff"}]
    assert result["small_clusters"] == []


async def test_find_stray_pixels_diagonal_neighbours_connect(call):
    await new_sprite(call, 4, 4)
    await put(call, (1, 1, RED), (2, 2, RED))

    result = await call("find_stray_pixels", path="a.aseprite")

    assert result["lone_pixels"] == []
    assert result["small_clusters"] == [
        {"x": 1, "y": 1, "w": 2, "h": 2, "size": 2, "pixels": [[1, 1], [2, 2]]}
    ]


async def test_find_stray_pixels_skips_clusters_of_four(call):
    await new_sprite(call, 8, 4)
    await put(call, (0, 0, RED), (1, 0, RED), (2, 0, RED))
    await put(call, (5, 0, RED), (6, 0, RED), (5, 1, RED), (6, 1, RED))

    result = await call("find_stray_pixels", path="a.aseprite")

    assert [c["size"] for c in result["small_clusters"]] == [3]


async def test_find_stray_pixels_lists_at_most_50(call):
    await new_sprite(call, 20, 12)
    dots = [(x, y, RED) for y in range(0, 12, 2) for x in range(0, 20, 2)]
    await put(call, *dots)

    result = await call("find_stray_pixels", path="a.aseprite")

    assert len(result["lone_pixels"]) == 50
    assert result["lone_pixel_count"] == 60
    assert result["lone_pixels_truncated"] is True
    assert result["lone_pixels"][0] == {"x": 0, "y": 0, "color": "#ff0000"}


async def test_read_tools_in_one_batch(call):
    await new_sprite(call, 4, 4)
    entries = [
        {"tool": "draw_pixels", "args": {"pixels": [{"x": 2, "y": 1, "color": RED}]}},
        {"tool": "read_pixels", "args": {"rect": rect(2, 1, 1, 1), "format": "hex"}},
        {"tool": "get_bounds", "args": {}},
        {"tool": "compare_frames", "args": {"frame_a": 1, "frame_b": 1}},
        {"tool": "get_color_stats", "args": {"top": 1}},
        {"tool": "find_stray_pixels", "args": {}},
    ]

    result = (await call("batch", path="a.aseprite", ops=entries))["result"]

    assert result[1]["rows"] == ["#ff0000"]
    assert result[2]["bounds"] == {"x": 2, "y": 1, "w": 1, "h": 1}
    assert result[3]["identical"] is True
    assert result[4]["colors"][0]["color"] == "#ff0000"
    assert result[5]["lone_pixels"] == [{"x": 2, "y": 1, "color": "#ff0000"}]
