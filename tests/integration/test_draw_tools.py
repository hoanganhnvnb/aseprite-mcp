from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.errors import ToolError

RED = [255, 0, 0, 255]
BLUE = [0, 0, 255, 255]
GREEN = [0, 255, 0, 255]
CLEAR = [0, 0, 0, 0]


async def new_sprite(call, w: int = 8, h: int = 8, **args) -> None:
    await call("create_sprite", path="a.aseprite", width=w, height=h, **args)


def px(x: int, y: int, color: str) -> dict:
    return {"x": x, "y": y, "color": color}


def pts(*coords: tuple[int, int]) -> list[dict]:
    return [{"x": x, "y": y} for x, y in coords]


async def test_draw_pixels_outside_cel_grows_cel(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 16, 16)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(0, 0, *RED), (3, 3, *RED)])

    result = await call("draw_pixels", path="a.aseprite", pixels=[px(10, 10, "#0000ff")])

    assert result == {"layer": "Layer 1", "frame": 1, "painted": 1, "skipped_outside": 0}
    assert await pixels(path, read=[(0, 0), (3, 3), (10, 10)]) == [RED, RED, BLUE]
    cel = (await cels(path))[0]
    assert (cel["x"], cel["y"], cel["width"], cel["height"]) == (0, 0, 11, 11)


async def test_draw_pixels_keeps_offcanvas_content(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(-2, -2, *RED)])

    await call("draw_pixels", path="a.aseprite", pixels=[px(5, 5, "#0000ff")])

    assert await pixels(path, read=[(-2, -2), (5, 5)]) == [RED, BLUE]


async def test_draw_pixels_ignores_pixels_outside_canvas_and_counts_them(
    call, pixels, tmp_path: Path
):
    await new_sprite(call)

    result = await call(
        "draw_pixels",
        path="a.aseprite",
        pixels=[px(-1, 0, "#ff0000"), px(8, 3, "#ff0000"), px(2, 2, "#ff0000")],
    )

    assert (result["painted"], result["skipped_outside"]) == (1, 2)
    assert await pixels(tmp_path / "a.aseprite", read=[(2, 2)]) == [RED]


async def test_draw_pixels_on_indexed_sprite(call, pixels, set_palette, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (0, 0, 255, 255)])

    await call("draw_pixels", path="a.aseprite", pixels=[px(1, 1, "#ff0000"), px(2, 2, "#0000ff")])
    await call("draw_pixels", path="a.aseprite", pixels=[px(2, 2, "transparent")])

    assert await pixels(path, read=[(1, 1), (2, 2)], values=True) == [1, 0]


async def test_draw_pixels_on_gray_sprite(call, pixels, tmp_path: Path):
    await new_sprite(call, color_mode="grayscale")

    await call(
        "draw_pixels", path="a.aseprite", pixels=[px(0, 0, "#ff0000"), px(1, 0, "#80808080")]
    )

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0)]) == [
        [54, 54, 54, 255],
        [128, 128, 128, 128],
    ]


async def test_draw_pixels_too_many(call, monkeypatch: pytest.MonkeyPatch):
    await new_sprite(call)

    async def no_run(*args, **kwargs):
        raise AssertionError("Aseprite should not run")

    monkeypatch.setattr(ops, "run_script", no_run)
    many = [px(0, 0, "#ff0000")] * 16385

    with pytest.raises(ToolError, match="at most 16384"):
        await call("draw_pixels", path="a.aseprite", pixels=many)


async def test_draw_pixels_rejects_string_coordinates(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="valid integer"):
        await call(
            "draw_pixels",
            path="a.aseprite",
            pixels=[{"x": "0) os.execute('x') --", "y": 0, "color": "#ff0000"}],
        )


async def test_draw_missing_cel_without_create_fails(call):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)

    with pytest.raises(ToolError, match="'Layer 1' has no cel in frame 2"):
        await call(
            "draw_pixels",
            path="a.aseprite",
            pixels=[px(0, 0, "#ff0000")],
            frame=2,
            create_cel=False,
        )


async def test_draw_missing_cel_is_created(call, pixels, tmp_path: Path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)

    await call("draw_pixels", path="a.aseprite", pixels=[px(3, 4, "#ff0000")], frame=2)

    assert await pixels(tmp_path / "a.aseprite", read=[(3, 4)], frame=2) == [RED]


async def test_draw_defaults_to_first_normal_layer(call, pixels, tmp_path: Path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="Tiles", kind="tilemap", tile_size=4)
    await call("update_layer", path="a.aseprite", layer="Tiles", stack_index=1)
    await call("add_layer", path="a.aseprite", name="Top")

    result = await call("draw_pixels", path="a.aseprite", pixels=[px(1, 1, "#ff0000")])

    assert result["layer"] == "Layer 1"
    assert await pixels(tmp_path / "a.aseprite", read=[(1, 1)], layer="Layer 1") == [RED]


async def test_draw_on_group_layer_fails(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")

    with pytest.raises(ToolError, match="'G' is a group"):
        await call("draw_pixels", path="a.aseprite", pixels=[px(0, 0, "#ff0000")], layer="G")


async def test_draw_on_tilemap_layer_fails(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="Tiles", kind="tilemap", tile_size=4)

    with pytest.raises(ToolError, match="'Tiles' is a tilemap layer"):
        await call(
            "draw_rect",
            path="a.aseprite",
            rect={"x": 0, "y": 0, "w": 2, "h": 2},
            color="#ff0000",
            layer="Tiles",
        )


async def test_draw_on_linked_cel_does_not_touch_other_frames(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    await pixels(path, put=[(1, 1, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)

    await call("draw_pixels", path="a.aseprite", pixels=[px(5, 5, "#0000ff")], frame=2)

    assert await pixels(path, read=[(5, 5), (1, 1)], frame=1) == [CLEAR, RED]
    assert await pixels(path, read=[(5, 5), (1, 1)], frame=2) == [BLUE, RED]
    assert await pixels(path, read=[(5, 5)], frame=3) == [CLEAR]
    first, second, third = await cels(path)
    assert first["image_id"] == third["image_id"] != second["image_id"]


async def test_draw_line_horizontal(call, grid, tmp_path: Path):
    await new_sprite(call, 8, 3)

    result = await call(
        "draw_line",
        path="a.aseprite",
        points=pts((1, 1), (5, 1)),
        color="#ff0000",
    )

    assert result["painted"] == 5
    assert await grid(tmp_path / "a.aseprite") == ["........", ".#####..", "........"]


async def test_draw_line_diagonal_has_no_gaps(call, grid, tmp_path: Path):
    await new_sprite(call, 8, 4)

    await call(
        "draw_line",
        path="a.aseprite",
        points=pts((0, 0), (7, 3)),
        color="#ff0000",
    )

    assert await grid(tmp_path / "a.aseprite") == [
        "##......",
        "..##....",
        "....##..",
        "......##",
    ]


async def test_draw_line_even_thickness_exact_width(call, grid, tmp_path: Path):
    await new_sprite(call, 12, 10)

    await call(
        "draw_line",
        path="a.aseprite",
        points=pts((2, 4), (8, 4)),
        color="#ff0000",
        thickness=4,
    )

    rows = await grid(tmp_path / "a.aseprite")
    assert [y for y, row in enumerate(rows) if "#" in row] == [3, 4, 5, 6]
    assert rows[3] == ".##########."


async def test_draw_line_closed_connects_last_point(call, grid, tmp_path: Path):
    await new_sprite(call, 5, 5)

    await call(
        "draw_line",
        path="a.aseprite",
        points=pts((0, 0), (4, 0), (0, 4)),
        color="#ff0000",
        closed=True,
    )

    assert await grid(tmp_path / "a.aseprite") == ["#####", "#..#.", "#.#..", "##...", "#...."]


async def test_draw_rect_outline_and_fill(call, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 6, 5)
    rect = {"x": 1, "y": 1, "w": 4, "h": 3}

    await call("draw_rect", path="a.aseprite", rect=rect, color="#ff0000")
    outline = await grid(path)
    await call("draw_rect", path="a.aseprite", rect=rect, color="#ff0000", fill=True)

    assert outline == ["......", ".####.", ".#..#.", ".####.", "......"]
    assert await grid(path) == ["......", ".####.", ".####.", ".####.", "......"]


async def test_draw_rect_thickness(call, grid, tmp_path: Path):
    await new_sprite(call, 6, 6)

    await call(
        "draw_rect",
        path="a.aseprite",
        rect={"x": 0, "y": 0, "w": 6, "h": 6},
        color="#ff0000",
        thickness=2,
    )

    assert await grid(tmp_path / "a.aseprite") == [
        "######",
        "######",
        "##..##",
        "##..##",
        "######",
        "######",
    ]


async def test_draw_rect_is_clipped_to_canvas(call, grid, tmp_path: Path):
    await new_sprite(call, 4, 3)

    result = await call(
        "draw_rect",
        path="a.aseprite",
        rect={"x": -2, "y": 1, "w": 4, "h": 10},
        color="#ff0000",
        fill=True,
    )

    assert result["painted"] == 4
    assert await grid(tmp_path / "a.aseprite") == ["....", "##..", "##.."]


async def test_draw_ellipse_zero_radius_is_one_pixel(call, grid, tmp_path: Path):
    await new_sprite(call, 5, 3)

    result = await call("draw_ellipse", path="a.aseprite", cx=3, cy=1, rx=0, ry=0, color="#ff0000")

    assert result["painted"] == 1
    assert await grid(tmp_path / "a.aseprite") == [".....", "...#.", "....."]


async def test_draw_ellipse_filled_has_no_holes(call, grid, tmp_path: Path):
    await new_sprite(call, 13, 9)

    await call(
        "draw_ellipse", path="a.aseprite", cx=6, cy=4, rx=6, ry=4, color="#ff0000", fill=True
    )

    rows = await grid(tmp_path / "a.aseprite")
    assert rows[4] == "#############"
    assert all("." not in row.strip(".") for row in rows)
    assert rows[0].count("#") > 0 and rows[8] == rows[0]


async def test_draw_ellipse_outline_is_border_of_fill(call, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 15, 9)
    await call("add_layer", path="a.aseprite", name="Fill")
    shape = {"cx": 7, "cy": 4, "rx": 7, "ry": 4, "color": "#ff0000"}

    await call("draw_ellipse", path="a.aseprite", **shape)
    await call("draw_ellipse", path="a.aseprite", layer="Fill", fill=True, **shape)

    filled = await grid(path, layer="Fill")

    def inside(x: int, y: int) -> bool:
        return 0 <= y < len(filled) and 0 <= x < len(filled[0]) and filled[y][x] == "#"

    border = [
        "".join(
            "#"
            if inside(x, y)
            and not all(inside(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            else "."
            for x in range(len(filled[0]))
        )
        for y in range(len(filled))
    ]
    assert await grid(path) == border


async def test_draw_circle_is_symmetric(call, grid, tmp_path: Path):
    await new_sprite(call, 11, 11)

    await call("draw_ellipse", path="a.aseprite", cx=5, cy=5, rx=5, ry=5, color="#ff0000")

    rows = await grid(tmp_path / "a.aseprite")
    assert rows == rows[::-1]
    assert rows == [row[::-1] for row in rows]
    assert rows == ["".join(col) for col in zip(*rows)]


async def test_draw_polygon_triangle_fill_count(call, grid, tmp_path: Path):
    await new_sprite(call, 6, 6)

    result = await call(
        "draw_polygon",
        path="a.aseprite",
        points=pts((0, 0), (4, 0), (0, 4)),
        color="#ff0000",
    )

    assert result["painted"] == 15
    assert (await grid(tmp_path / "a.aseprite"))[2] == "###..."


async def test_draw_polygon_outline(call, grid, tmp_path: Path):
    await new_sprite(call, 5, 5)

    await call(
        "draw_polygon",
        path="a.aseprite",
        points=pts((0, 0), (4, 0), (4, 4), (0, 4)),
        color="#ff0000",
        fill=False,
    )

    assert await grid(tmp_path / "a.aseprite") == ["#####", "#...#", "#...#", "#...#", "#####"]


async def test_draw_polygon_self_intersecting_does_not_fail(call, pixels, tmp_path: Path):
    await new_sprite(call, 7, 7)

    result = await call(
        "draw_polygon",
        path="a.aseprite",
        points=pts((0, 0), (6, 6), (6, 0), (0, 6)),
        color="#ff0000",
    )

    assert result["painted"] > 0
    assert await pixels(tmp_path / "a.aseprite", read=[(3, 3), (1, 3), (3, 1)]) == [RED, RED, CLEAR]


async def test_fill_area_contiguous_stops_at_walls(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 7, 5)
    await call(
        "draw_line",
        path="a.aseprite",
        points=pts((3, 0), (3, 4)),
        color="#ff0000",
    )

    result = await call("fill_area", path="a.aseprite", x=0, y=0, color="#0000ff")

    assert result["painted"] == 15
    assert await pixels(path, read=[(1, 1), (3, 2), (5, 1)]) == [BLUE, RED, CLEAR]


async def test_fill_area_non_contiguous_hits_all_matches(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED), (4, 4, *RED)])

    result = await call("fill_area", path="a.aseprite", x=0, y=0, color="#0000ff", contiguous=False)

    assert result["painted"] == 2
    assert await pixels(path, read=[(0, 0), (4, 4)]) == [BLUE, BLUE]


async def test_fill_area_tolerance(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call(
        "draw_pixels",
        path="a.aseprite",
        pixels=[px(0, 0, "#ff0000"), px(1, 0, "#f50000"), px(2, 0, "#f00000")],
    )

    await call("fill_area", path="a.aseprite", x=0, y=0, color="#00ff00", tolerance=10)

    assert await pixels(path, read=[(0, 0), (1, 0), (2, 0)]) == [
        GREEN,
        GREEN,
        [240, 0, 0, 255],
    ]


async def test_fill_area_on_empty_cel_is_bounded_by_canvas(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 8, 6)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(1, 1, *RED)])

    result = await call("fill_area", path="a.aseprite", x=5, y=4, color="#0000ff")

    assert result["painted"] == 47
    cel = (await cels(path))[0]
    assert (cel["x"], cel["y"], cel["width"], cel["height"]) == (0, 0, 8, 6)
    assert await pixels(path, read=[(1, 1), (0, 0), (7, 5)]) == [RED, BLUE, BLUE]


async def test_fill_area_seed_outside_canvas_fails(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="outside the canvas"):
        await call("fill_area", path="a.aseprite", x=8, y=0, color="#0000ff")


async def test_blend_true_mixes_alpha(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *BLUE)])

    await call(
        "draw_rect",
        path="a.aseprite",
        rect={"x": 0, "y": 0, "w": 1, "h": 1},
        color="#ff000080",
        fill=True,
        blend=True,
    )

    assert await pixels(path, read=[(0, 0)]) == [[128, 0, 127, 255]]


async def test_blend_false_overwrites(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *BLUE)])

    await call(
        "draw_rect",
        path="a.aseprite",
        rect={"x": 0, "y": 0, "w": 1, "h": 1},
        color="#ff000080",
        fill=True,
    )

    assert await pixels(path, read=[(0, 0)]) == [[255, 0, 0, 128]]


async def test_draw_tools_in_one_batch(call, pixels, tmp_path: Path, monkeypatch):
    await new_sprite(call)
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
            {
                "tool": "draw_rect",
                "args": {"rect": {"x": 0, "y": 0, "w": 4, "h": 4}, "color": "#ff0000"},
            },
            {"tool": "fill_area", "args": {"x": 1, "y": 1, "color": "#0000ff"}},
            {"tool": "draw_pixels", "args": {"pixels": [px(6, 6, "#00ff00")]}},
            {"tool": "draw_line", "args": {"points": pts((7, 0), (7, 2)), "color": "#00ff00"}},
        ],
    )

    assert len(calls) == 1
    assert [r["painted"] for r in result["result"]] == [12, 4, 1, 3]
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (2, 2), (6, 6), (7, 1)]) == [
        RED,
        BLUE,
        GREEN,
        GREEN,
    ]
