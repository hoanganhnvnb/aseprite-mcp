from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.colors import PALETTES
from aseprite_mcp.errors import ToolError
from aseprite_mcp.tools.color import CONVOLUTION_MATRICES

RED = [255, 0, 0, 255]
BLUE = [0, 0, 255, 255]
GREEN = [0, 255, 0, 255]
BLACK = [0, 0, 0, 255]
WHITE = [255, 255, 255, 255]
CLEAR = [0, 0, 0, 0]


async def new_sprite(call, w: int = 4, h: int = 4, **args) -> None:
    await call("create_sprite", path="a.aseprite", width=w, height=h, **args)


def rect(x: int, y: int, w: int, h: int) -> dict:
    return {"x": x, "y": y, "w": w, "h": h}


def swap(a: str, b: str) -> list[dict]:
    return [{"from": a, "to": b}, {"from": b, "to": a}]


async def test_set_palette_and_get_palette_round_trip(call):
    await new_sprite(call)

    await call("set_palette", path="a.aseprite", colors=["#ff0000", "#00FF0080", "transparent"])
    result = await call("get_palette", path="a.aseprite")

    assert result == {"colors": ["#ff0000", "#00ff0080", "#00000000"], "size": 3}


async def test_set_palette_preset(call):
    await new_sprite(call)

    result = await call("set_palette", path="a.aseprite", preset="gameboy")

    assert result == {"size": 4}
    assert (await call("get_palette", path="a.aseprite"))["colors"] == PALETTES["gameboy"]


async def test_get_palette_indexed_reports_transparent_index(call):
    await new_sprite(call, color_mode="indexed")

    result = await call("get_palette", path="a.aseprite")

    assert result["transparent_index"] == 1
    assert result["colors"][0] == "#00000000"


async def test_set_palette_indexed_keeps_pixel_indices(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["transparent", "#ff0000", "#0000ff"])
    await pixels(path, put=[(0, 0, *BLUE)])

    await call("set_palette", path="a.aseprite", colors=["transparent", "#ffffff", "#00ff00"])

    assert await pixels(path, read=[(0, 0)], values=True) == [2]
    assert await pixels(path, read=[(0, 0)]) == [GREEN]


async def test_set_palette_indexed_refuses_dropping_a_used_entry(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["transparent", "#ff0000", "#0000ff"])
    await pixels(path, put=[(0, 0, *BLUE)])

    with pytest.raises(ToolError, match="palette index 3"):
        await call("set_palette", path="a.aseprite", colors=["transparent", "#ffffff"])


async def test_replace_colors_exact_match(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED), (1, 0, 254, 0, 0, 255)])

    result = await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        mappings=[{"from": "#ff0000", "to": "#0000ff"}],
    )

    assert result == {"layer": "Layer 1", "cels": 1, "replaced": 1, "skipped_frames": 0}
    assert await pixels(path, read=[(0, 0), (1, 0)]) == [BLUE, [254, 0, 0, 255]]


async def test_replace_colors_tolerance_is_per_channel(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, 245, 10, 0, 255), (1, 0, 240, 0, 0, 255)])

    result = await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        mappings=[{"from": "#ff0000", "to": "#0000ff"}],
        tolerance=10,
    )

    assert result["replaced"] == 1
    assert await pixels(path, read=[(0, 0), (1, 0)]) == [BLUE, [240, 0, 0, 255]]


async def test_replace_colors_swaps_two_colours(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED), (1, 0, *BLUE)])

    await call(
        "replace_colors", path="a.aseprite", layer="Layer 1", mappings=swap("#ff0000", "#0000ff")
    )

    assert await pixels(path, read=[(0, 0), (1, 0)]) == [BLUE, RED]


async def test_replace_colors_to_transparent_erases(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])

    await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        mappings=[{"from": "#ff0000", "to": "transparent"}],
    )

    assert await pixels(path, read=[(0, 0)]) == [CLEAR]


async def test_replace_colors_to_transparent_on_background_paints_black(
    call, pixels, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, background="#ffffff")
    await pixels(path, background=True)

    await call(
        "replace_colors",
        path="a.aseprite",
        layer="Background",
        mappings=[{"from": "#ffffff", "to": "transparent"}],
    )

    assert await pixels(path, read=[(0, 0)], layer="Background") == [BLACK]


async def test_replace_colors_only_inside_region(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED), (3, 3, *RED)])

    result = await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        mappings=[{"from": "#ff0000", "to": "#00ff00"}],
        region=rect(2, 2, 5, 5),
    )

    assert result["replaced"] == 1
    assert await pixels(path, read=[(0, 0), (3, 3)]) == [RED, GREEN]


async def test_replace_colors_indexed(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    palette = ["transparent", "#ff0000", "#0000ff", "#00ff00"]
    await call("set_palette", path="a.aseprite", colors=palette)
    await pixels(path, put=[(0, 0, *RED), (1, 0, *BLUE)])

    await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        mappings=[{"from": "#ff0000", "to": "#10f010"}],
    )

    assert await pixels(path, read=[(0, 0), (1, 0)], values=True) == [3, 2]
    assert (await call("get_palette", path="a.aseprite"))["colors"] == [
        "#00000000",
        "#ff0000",
        "#0000ff",
        "#00ff00",
    ]


async def test_replace_colors_grayscale(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="grayscale")
    await pixels(path, put=[(0, 0, 128, 128, 128, 255)])

    await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        mappings=[{"from": "#808080", "to": "#ffffff"}],
    )

    assert await pixels(path, read=[(0, 0)]) == [WHITE]


async def test_replace_colors_region_outside_canvas_fails(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="outside the canvas"):
        await call(
            "replace_colors",
            path="a.aseprite",
            layer="Layer 1",
            mappings=[{"from": "#ff0000", "to": "#00ff00"}],
            region=rect(10, 10, 2, 2),
        )


async def test_replace_colors_swap_on_linked_cels(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await pixels(path, put=[(0, 0, *RED), (1, 0, *BLUE)])
    await call("copy_frames", path="a.aseprite", source=1, targets=2, link=True)

    result = await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        frames="all",
        mappings=swap("#ff0000", "#0000ff"),
    )

    assert result["cels"] == 1
    for frame in (1, 2):
        assert await pixels(path, read=[(0, 0), (1, 0)], frame=frame) == [BLUE, RED]
    first, second = await cels(path)
    assert first["image_id"] == second["image_id"]


async def test_replace_colors_on_one_linked_frame_keeps_the_other(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await pixels(path, put=[(0, 0, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets=2, link=True)

    await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        frames=2,
        mappings=[{"from": "#ff0000", "to": "#00ff00"}],
    )

    assert await pixels(path, read=[(0, 0)], frame=1) == [RED]
    assert await pixels(path, read=[(0, 0)], frame=2) == [GREEN]


async def test_replace_colors_on_two_of_three_linked_frames(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    await pixels(path, put=[(0, 0, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)

    result = await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        frames="1-2",
        mappings=[{"from": "#ff0000", "to": "#00ff00"}],
    )

    assert (result["cels"], result["replaced"]) == (2, 2)
    for frame, expected in ((1, GREEN), (2, GREEN), (3, RED)):
        assert await pixels(path, read=[(0, 0)], frame=frame) == [expected]


async def test_adjust_invert(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, 200, 100, 50, 128)])

    result = await call("adjust_colors", path="a.aseprite", layer="Layer 1", invert=True)

    assert result == {"layer": "Layer 1", "cels": 1}
    assert await pixels(path, read=[(0, 0)]) == [[55, 155, 205, 128]]


async def test_adjust_hue(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, 200, 100, 50, 255)])

    await call("adjust_colors", path="a.aseprite", layer="Layer 1", hue=180)

    assert await pixels(path, read=[(0, 0)]) == [[50, 150, 200, 255]]


async def test_adjust_brightness(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, 200, 100, 50, 255)])

    await call("adjust_colors", path="a.aseprite", layer="Layer 1", brightness=50)

    assert await pixels(path, read=[(0, 0)]) == [[255, 150, 75, 255]]


async def test_adjust_inverts_after_shifting_hue(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, 200, 100, 50, 255)])

    await call("adjust_colors", path="a.aseprite", layer="Layer 1", hue=180, invert=True)

    assert await pixels(path, read=[(0, 0)]) == [[205, 105, 55, 255]]


async def test_adjust_only_inside_region(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED), (3, 3, *RED)])

    await call(
        "adjust_colors", path="a.aseprite", layer="Layer 1", invert=True, region=rect(0, 0, 2, 2)
    )

    assert await pixels(path, read=[(0, 0), (3, 3)]) == [[0, 255, 255, 255], RED]


async def test_adjust_hidden_layer(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])
    await call("update_layer", path="a.aseprite", layer="Layer 1", visible=False)

    await call("adjust_colors", path="a.aseprite", layer="Layer 1", invert=True)

    assert await pixels(path, read=[(0, 0)]) == [[0, 255, 255, 255]]
    info = await call("get_sprite_info", path="a.aseprite")
    assert info["layers"][0]["visible"] is False


async def test_adjust_missing_cel_errors(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=2)
    await pixels(path, put=[(0, 0, *RED)])

    with pytest.raises(ToolError, match="'Layer 1' has no cel in frame 2"):
        await call("adjust_colors", path="a.aseprite", layer="Layer 1", frames="all", invert=True)

    assert await pixels(path, read=[(0, 0)]) == [RED]


async def test_adjust_refuses_locked_layer(call, pixels, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])
    await locks(path, lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call("adjust_colors", path="a.aseprite", layer="Layer 1", invert=True)


async def test_adjust_refuses_group(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")

    with pytest.raises(ToolError, match="'G' is a group"):
        await call("adjust_colors", path="a.aseprite", layer="G", invert=True)


async def test_adjust_hue_refused_on_indexed_sprite(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await pixels(path, put=[(0, 0, *RED)])

    with pytest.raises(ToolError, match="indexed"):
        await call("adjust_colors", path="a.aseprite", layer="Layer 1", hue=90)


async def test_adjust_invert_on_indexed_sprite_picks_palette_entries(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["transparent", "#ff0000", "#00ffff"])
    await pixels(path, put=[(0, 0, *RED)])

    await call("adjust_colors", path="a.aseprite", layer="Layer 1", invert=True)

    assert await pixels(path, read=[(0, 0)], values=True) == [2]
    assert await pixels(path, read=[(1, 0)]) == [CLEAR]


async def test_outline_outside_square(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 7, 7)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(x, y, *RED) for x in (2, 3, 4) for y in (2, 3, 4)])

    result = await call(
        "outline", path="a.aseprite", layer="Layer 1", color="#0000ff", matrix="square"
    )

    assert result == {"layer": "Layer 1", "cels": 1}
    assert await grid(path) == [
        ".......",
        ".#####.",
        ".#####.",
        ".#####.",
        ".#####.",
        ".#####.",
        ".......",
    ]
    assert await pixels(path, read=[(1, 1), (2, 2)]) == [BLUE, RED]


async def test_outline_circle_leaves_corners(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 5)
    await pixels(path, put=[(2, 2, *RED)])

    await call("outline", path="a.aseprite", layer="Layer 1", color="#0000ff")

    assert await grid(path) == [
        ".....",
        "..#..",
        ".###.",
        "..#..",
        ".....",
    ]


async def test_outline_inside_recolours_the_edge(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 5)
    await pixels(path, put=[(x, y, *RED) for x in (1, 2, 3) for y in (1, 2, 3)])

    await call(
        "outline",
        path="a.aseprite",
        layer="Layer 1",
        color="#0000ff",
        place="inside",
        matrix="square",
    )

    assert await pixels(path, read=[(1, 1), (2, 2), (0, 0)]) == [BLUE, RED, CLEAR]


async def test_outline_region_only(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 7, 7)
    await pixels(path, put=[(x, y, *RED) for x in (2, 3, 4) for y in (2, 3, 4)])

    await call(
        "outline",
        path="a.aseprite",
        layer="Layer 1",
        color="#0000ff",
        region=rect(0, 0, 7, 3),
    )

    assert await grid(path) == [
        ".......",
        "..###..",
        ".#####.",
        "..###..",
        "..###..",
        ".......",
        ".......",
    ]


async def test_outline_refuses_background_layer(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, background="#ffffff")
    await pixels(path, background=True)

    with pytest.raises(ToolError, match="background"):
        await call("outline", path="a.aseprite", layer="Background", color="#0000ff")


async def test_outline_on_indexed_sprite_uses_the_palette_entry(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 3, 3, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["transparent", "#ff0000", "#0000ff"])
    await pixels(path, put=[(1, 1, *RED)])

    await call("outline", path="a.aseprite", layer="Layer 1", color="#0000ff", matrix="square")

    assert await pixels(path, read=[(0, 0), (1, 1)], values=True) == [2, 1]


async def test_apply_convolution_blur(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 5, background="#000000")
    await pixels(path, put=[(2, 2, *WHITE)])

    result = await call("apply_convolution", path="a.aseprite", layer="Layer 1", matrix="blur-3x3")

    assert result == {"layer": "Layer 1", "cels": 1}
    assert await pixels(path, read=[(2, 2), (1, 2), (0, 0)]) == [
        [63, 63, 63, 255],
        [31, 31, 31, 255],
        BLACK,
    ]


async def test_apply_convolution_keeps_background_opaque(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 3, 3, background="#000000")
    await pixels(path, put=[(1, 1, *WHITE)], background=True)

    await call("apply_convolution", path="a.aseprite", layer="Background", matrix="edges-find")

    read = await pixels(path, read=[(1, 1), (0, 0)], layer="Background")
    assert [alpha for *_, alpha in read] == [255, 255]


async def test_every_convolution_matrix_is_accepted(call, pixels, images, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 6, 6)
    count = len(CONVOLUTION_MATRICES)
    pattern = [
        (x, y, (x * 53 + y * 17) % 256, (x * 31 + y * 97) % 256, (x * 7 + y * 131) % 256, 255)
        for x in range(6)
        for y in range(6)
        if (x + y) % 3
    ]
    await pixels(path, put=pattern)
    await call("add_frames", path="a.aseprite", count=count)
    await call("copy_frames", path="a.aseprite", source=1, targets=f"2-{count + 1}")

    await call(
        "batch",
        path="a.aseprite",
        ops=[
            {
                "tool": "apply_convolution",
                "args": {"layer": "Layer 1", "frames": i, "matrix": name},
            }
            for i, name in enumerate(CONVOLUTION_MATRICES, 2)
        ],
    )

    source, *filtered = await images(path)
    unchanged = [name for name, image in zip(CONVOLUTION_MATRICES, filtered) if image == source]
    assert unchanged == []


async def test_quantize_to_palette_snaps_to_nearest(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("set_palette", path="a.aseprite", colors=["#000000", "#ffffff", "#ff0000"])
    await pixels(path, put=[(0, 0, 200, 30, 30, 255), (1, 0, 30, 30, 30, 128), (2, 0, *RED)])

    result = await call("quantize_to_palette", path="a.aseprite", layer="Layer 1")

    assert result == {"layer": "Layer 1", "cels": 1, "changed": 2, "skipped_frames": 0}
    assert await pixels(path, read=[(0, 0), (1, 0), (2, 0), (3, 0)]) == [
        RED,
        [0, 0, 0, 128],
        RED,
        CLEAR,
    ]


async def test_quantize_to_palette_refuses_indexed_sprite(call):
    await new_sprite(call, color_mode="indexed")

    with pytest.raises(ToolError, match="indexed"):
        await call("quantize_to_palette", path="a.aseprite", layer="Layer 1")


async def test_extract_palette_finds_the_used_colours(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED), (1, 0, *BLUE), (2, 0, *GREEN)])

    result = await call("extract_palette", path="a.aseprite", max_colors=8)

    assert sorted(result["colors"]) == ["#0000ff", "#00ff00", "#ff0000"]


async def test_extract_palette_from_indexed_sprite(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await call("set_palette", path="a.aseprite", colors=["transparent", "#ff0000", "#0000ff"])
    await pixels(path, put=[(0, 0, *RED)])

    result = await call("extract_palette", path="a.aseprite", max_colors=4)

    assert result == {"colors": ["#ff0000"]}
    assert (await call("get_palette", path="a.aseprite"))["size"] == 3


async def test_extract_palette_stays_within_max_colors(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(x, 0, x * 60, 255 - x * 60, 0, 255) for x in range(4)])

    result = await call("extract_palette", path="a.aseprite", max_colors=2)

    assert 1 <= len(result["colors"]) <= 2


async def test_extract_palette_leaves_the_sprite_palette(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("set_palette", path="a.aseprite", preset="pico8")
    await pixels(path, put=[(0, 0, 1, 2, 3, 255)])

    await call(
        "batch",
        path="a.aseprite",
        ops=[
            {"tool": "extract_palette", "args": {"max_colors": 4}},
            {"tool": "adjust_colors", "args": {"layer": "Layer 1", "invert": True}},
        ],
    )

    assert (await call("get_palette", path="a.aseprite"))["colors"] == PALETTES["pico8"]


async def test_color_tools_in_one_batch(call, pixels, tmp_path: Path, monkeypatch):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 5)
    await pixels(path, put=[(2, 2, *RED)])
    calls = []
    real_run_script = ops.run_script

    async def counting_run_script(*args, **kwargs):
        calls.append(args[0])
        return await real_run_script(*args, **kwargs)

    monkeypatch.setattr(ops, "run_script", counting_run_script)

    result = await call(
        "batch",
        path="a.aseprite",
        ops=[
            {"tool": "set_palette", "args": {"preset": "pico8"}},
            {
                "tool": "replace_colors",
                "args": {"layer": "Layer 1", "mappings": [{"from": "#ff0000", "to": "#ffffff"}]},
            },
            {"tool": "adjust_colors", "args": {"layer": "Layer 1", "invert": True}},
            {"tool": "outline", "args": {"layer": "Layer 1", "color": "#ff004d"}},
            {"tool": "quantize_to_palette", "args": {"layer": "Layer 1"}},
            {"tool": "get_palette", "args": {}},
        ],
    )

    assert len(calls) == 1
    assert result["result"][5]["size"] == 16
    assert await pixels(path, read=[(2, 2), (2, 1), (0, 0)]) == [BLACK, [255, 0, 77, 255], CLEAR]


async def test_failing_colour_op_saves_nothing(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])

    with pytest.raises(ToolError, match="op 2"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "adjust_colors", "args": {"layer": "Layer 1", "invert": True}},
                {"tool": "outline", "args": {"layer": "Nope", "color": "#000000"}},
            ],
        )

    assert await pixels(path, read=[(0, 0)]) == [RED]


async def test_set_palette_refused_on_grayscale_sprite(call):
    await new_sprite(call, color_mode="grayscale")

    with pytest.raises(ToolError, match="grayscale"):
        await call("set_palette", path="a.aseprite", colors=["#000000", "#808080"])

    assert (await call("get_palette", path="a.aseprite"))["size"] == 256


async def test_quantize_to_palette_refuses_grayscale_sprite(call):
    await new_sprite(call, color_mode="grayscale")

    with pytest.raises(ToolError, match="grayscale"):
        await call("quantize_to_palette", path="a.aseprite", layer="Layer 1")


async def test_replace_colors_without_a_match_keeps_cels_linked(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await pixels(path, put=[(0, 0, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets=2, link=True)

    result = await call(
        "replace_colors",
        path="a.aseprite",
        layer="Layer 1",
        frames=1,
        mappings=[{"from": "#0000ff", "to": "#00ff00"}],
    )

    assert result["replaced"] == 0
    first, second = await cels(path)
    assert first["image_id"] == second["image_id"]


async def test_missing_cel_error_mentions_cels_emptied_earlier(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 5, background="#000000")
    await pixels(path, put=[(2, 2, *WHITE)])

    with pytest.raises(ToolError, match="emptied"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "apply_convolution", "args": {"layer": "Layer 1", "matrix": "edges-find"}},
                {"tool": "adjust_colors", "args": {"layer": "Layer 1", "invert": True}},
            ],
        )
