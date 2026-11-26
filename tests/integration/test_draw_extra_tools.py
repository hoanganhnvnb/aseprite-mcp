from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.errors import ToolError
from helpers import rect, sprite_maker

RED = [255, 0, 0, 255]
GREEN = [0, 255, 0, 255]
BLUE = [0, 0, 255, 255]
CLEAR = [0, 0, 0, 0]


new_sprite = sprite_maker(8, 8)


async def picture(pixels, path: Path, w: int, h: int, letters: dict) -> list[str]:
    """The canvas as text, one letter per known colour and '.' for transparent."""
    names = {tuple(color): letter for letter, color in letters.items()}
    names[tuple(CLEAR)] = "."
    coords = [(x, y) for y in range(h) for x in range(w)]
    found = await pixels(path, read=coords)
    chars = [names.get(tuple(c), "?") for c in found]
    return ["".join(chars[y * w : (y + 1) * w]) for y in range(h)]


async def test_gradient_horizontal_two_stops_endpoints_and_middle(call, pixels, tmp_path: Path):
    await new_sprite(call, 5, 1)

    result = await call(
        "draw_gradient", path="a.aseprite", rect=rect(0, 0, 5, 1), colors=["#000000", "#ffffff"]
    )

    assert result == {"layer": "Layer 1", "frame": 1, "painted": 5, "skipped_outside": 0}
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0), (2, 0), (4, 0)]) == [
        [0, 0, 0, 255],
        [64, 64, 64, 255],
        [128, 128, 128, 255],
        [255, 255, 255, 255],
    ]


async def test_gradient_vertical(call, pixels, tmp_path: Path):
    await new_sprite(call, 2, 3)

    await call(
        "draw_gradient",
        path="a.aseprite",
        rect=rect(0, 0, 2, 3),
        colors=["#ff0000", "#0000ff"],
        direction="vertical",
    )

    assert await pixels(tmp_path / "a.aseprite", read=[(1, 0), (1, 1), (0, 2)]) == [
        RED,
        [128, 0, 128, 255],
        BLUE,
    ]


async def test_gradient_three_stops_hits_middle_colour(call, pixels, tmp_path: Path):
    await new_sprite(call, 5, 1)

    await call(
        "draw_gradient",
        path="a.aseprite",
        rect=rect(0, 0, 5, 1),
        colors=["#ff0000", "#00ff00", "#0000ff"],
    )

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0), (2, 0), (4, 0)]) == [
        RED,
        [128, 128, 0, 255],
        GREEN,
        BLUE,
    ]


async def test_gradient_single_pixel_wide_rect(call, pixels, tmp_path: Path):
    await new_sprite(call, 4, 4)

    result = await call(
        "draw_gradient", path="a.aseprite", rect=rect(2, 0, 1, 3), colors=["#ff0000", "#0000ff"]
    )

    assert result["painted"] == 3
    assert await pixels(tmp_path / "a.aseprite", read=[(2, 0), (2, 2), (2, 3)]) == [
        RED,
        RED,
        CLEAR,
    ]


async def test_gradient_rect_partly_outside_canvas_is_clipped_with_full_span(
    call, pixels, tmp_path: Path
):
    await new_sprite(call, 3, 1)

    result = await call(
        "draw_gradient", path="a.aseprite", rect=rect(-2, 0, 5, 1), colors=["#000000", "#ffffff"]
    )

    assert (result["painted"], result["skipped_outside"]) == (3, 2)
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0), (2, 0)]) == [
        [128, 128, 128, 255],
        [191, 191, 191, 255],
        [255, 255, 255, 255],
    ]


async def test_gradient_huge_rect_is_clipped_before_painting(call, pixels, tmp_path: Path):
    await new_sprite(call, 4, 4)

    result = await call(
        "draw_gradient",
        path="a.aseprite",
        rect=rect(-65535, -65535, 131072, 131072),
        colors=["#000000", "#ffffff"],
        dither="bayer8",
    )

    assert result["painted"] == 16
    assert result["skipped_outside"] == 131072 * 131072 - 16


async def test_gradient_alpha_interpolates(call, pixels, tmp_path: Path):
    await new_sprite(call, 3, 1)

    await call(
        "draw_gradient", path="a.aseprite", rect=rect(0, 0, 3, 1), colors=["#ff000000", "#ff0000"]
    )

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0), (2, 0)]) == [
        [255, 0, 0, 0],
        [255, 0, 0, 128],
        RED,
    ]


async def test_gradient_on_indexed_sprite_uses_palette_entries(
    call, pixels, set_palette, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 3, 1, color_mode="indexed")
    await set_palette(
        path, [(0, 0, 0, 0), (0, 0, 0, 255), (255, 255, 255, 255), (120, 120, 120, 255)]
    )

    await call(
        "draw_gradient", path="a.aseprite", rect=rect(0, 0, 3, 1), colors=["#000000", "#ffffff"]
    )

    assert await pixels(path, read=[(0, 0), (1, 0), (2, 0)], values=True) == [1, 3, 2]


async def test_gradient_bayer_uses_only_the_two_neighbouring_colours(call, pixels, tmp_path: Path):
    await new_sprite(call, 9, 4)

    await call(
        "draw_gradient",
        path="a.aseprite",
        rect=rect(0, 0, 9, 4),
        colors=["#ff0000", "#00ff00", "#0000ff"],
        dither="bayer4",
    )

    rows = await picture(pixels, tmp_path / "a.aseprite", 9, 4, {"r": RED, "g": GREEN, "b": BLUE})
    assert [row[0] for row in rows] == ["r"] * 4
    assert [row[8] for row in rows] == ["b"] * 4
    assert set("".join(row[:4] for row in rows)) == {"r", "g"}
    assert set("".join(row[5:] for row in rows)) == {"g", "b"}


async def test_gradient_bayer2_exact_pattern(call, pixels, tmp_path: Path):
    await new_sprite(call, 6, 2)

    await call(
        "draw_gradient",
        path="a.aseprite",
        rect=rect(0, 0, 6, 2),
        colors=["#000000", "#ffffff"],
        dither="bayer2",
    )

    black, white = [0, 0, 0, 255], [255, 255, 255, 255]
    rows = await picture(pixels, tmp_path / "a.aseprite", 6, 2, {"k": black, "w": white})
    assert rows == ["kkwkww", "kkkwkw"]


async def test_gradient_rejects_one_colour(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="at least 2"):
        await call("draw_gradient", path="a.aseprite", rect=rect(0, 0, 4, 4), colors=["#ff0000"])


async def test_gradient_rejects_17_colours(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="at most 16"):
        await call(
            "draw_gradient", path="a.aseprite", rect=rect(0, 0, 4, 4), colors=["#ff0000"] * 17
        )


async def test_fill_pattern_density_zero_and_one(call, grid, tmp_path: Path):
    await new_sprite(call, 4, 2)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    await call(
        "fill_pattern",
        path="a.aseprite",
        rect=rect(0, 0, 4, 1),
        color_a="transparent",
        color_b="#ff0000",
        density=0,
    )
    await call(
        "fill_pattern",
        path="a.aseprite",
        rect=rect(0, 1, 4, 1),
        color_a="transparent",
        color_b="#ff0000",
        density=1,
    )

    assert await grid(tmp_path / "a.aseprite") == ["....", "####"]


async def test_fill_pattern_half_density_bayer2_is_checkerboard(call, grid, tmp_path: Path):
    await new_sprite(call, 4, 4)

    result = await call(
        "fill_pattern",
        path="a.aseprite",
        rect=rect(0, 0, 4, 4),
        color_a="transparent",
        color_b="#ff0000",
        density=0.5,
        matrix="bayer2",
    )

    assert result["painted"] == 16
    assert await grid(tmp_path / "a.aseprite") == ["#.#.", ".#.#", "#.#.", ".#.#"]


async def test_fill_pattern_tiles_seamlessly_across_calls(call, grid, tmp_path: Path):
    await new_sprite(call, 8, 8)
    await call("add_layer", path="a.aseprite", name="Whole")
    args = {"color_a": "transparent", "color_b": "#ff0000", "density": 0.3}

    await call("fill_pattern", path="a.aseprite", rect=rect(0, 0, 3, 8), **args)
    await call("fill_pattern", path="a.aseprite", rect=rect(3, 0, 5, 8), **args)
    await call("fill_pattern", path="a.aseprite", rect=rect(0, 0, 8, 8), layer="Whole", **args)

    halves = await grid(tmp_path / "a.aseprite")
    assert halves == await grid(tmp_path / "a.aseprite", layer="Whole")
    assert "#" in "".join(halves)


async def test_fill_pattern_density_out_of_range_fails(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="less than or equal to 1"):
        await call(
            "fill_pattern",
            path="a.aseprite",
            rect=rect(0, 0, 4, 4),
            color_a="#000000",
            color_b="#ffffff",
            density=1.5,
        )


async def test_fill_pattern_on_linked_cel_does_not_touch_other_frames(
    call, pixels, cels, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await call("add_frames", path="a.aseprite", count=1)
    await pixels(path, put=[(0, 0, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets=2, link=True)

    await call(
        "fill_pattern",
        path="a.aseprite",
        rect=rect(2, 2, 2, 2),
        color_a="#0000ff",
        color_b="#0000ff",
        density=0.5,
        frame=2,
    )

    assert await pixels(path, read=[(0, 0), (3, 3)], frame=1) == [RED, CLEAR]
    assert await pixels(path, read=[(0, 0), (3, 3)], frame=2) == [RED, BLUE]
    first, second = await cels(path)
    assert first["image_id"] != second["image_id"]


async def test_draw_ascii_paints_legend_colours(call, pixels, tmp_path: Path):
    await new_sprite(call, 4, 4)

    result = await call(
        "draw_ascii",
        path="a.aseprite",
        x=1,
        y=1,
        rows=["rg", "gr"],
        legend={"r": "#ff0000", "g": "#00ff00"},
    )

    assert result == {"layer": "Layer 1", "frame": 1, "painted": 4, "skipped_outside": 0}
    assert await pixels(tmp_path / "a.aseprite", read=[(1, 1), (2, 1), (1, 2), (2, 2)]) == [
        RED,
        GREEN,
        GREEN,
        RED,
    ]


async def test_draw_ascii_clips_runs_left_of_canvas(call, pixels, tmp_path: Path):
    await new_sprite(call, 4, 4)

    result = await call(
        "draw_ascii",
        path="a.aseprite",
        x=-2,
        y=-1,
        rows=["rrb", "rgb"],
        legend={"r": "#ff0000", "g": "#00ff00", "b": "#0000ff"},
    )

    assert (result["painted"], result["skipped_outside"]) == (1, 5)
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0)]) == [BLUE, CLEAR]


async def test_draw_ascii_dot_and_space_are_transparent(call, pixels, tmp_path: Path):
    await new_sprite(call, 2, 2)
    await call("draw_rect", path="a.aseprite", rect=rect(0, 0, 2, 2), color="#0000ff", fill=True)

    result = await call(
        "draw_ascii", path="a.aseprite", x=0, y=0, rows=["r.", " r"], legend={"r": "#ff0000"}
    )

    assert result["painted"] == 2
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0), (0, 1), (1, 1)]) == [
        RED,
        BLUE,
        BLUE,
        RED,
    ]


async def no_aseprite(*args, **kwargs):
    raise AssertionError("Aseprite should not run")


async def test_draw_ascii_unknown_char_names_row_and_column(call, monkeypatch):
    await new_sprite(call)
    monkeypatch.setattr(ops, "run_script", no_aseprite)

    with pytest.raises(ToolError, match="row 2, column 3: 'x' is not in the legend"):
        await call(
            "draw_ascii",
            path="a.aseprite",
            x=0,
            y=0,
            rows=["rrr", "r.x"],
            legend={"r": "#ff0000"},
        )


async def test_draw_ascii_legend_cannot_define_dot(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="'.' and ' ' always leave the pixel untouched"):
        await call("draw_ascii", path="a.aseprite", x=0, y=0, rows=["."], legend={".": "#ff0000"})


async def test_draw_ascii_multichar_legend_key_rejected(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="legend key 'rr' must be a single character"):
        await call("draw_ascii", path="a.aseprite", x=0, y=0, rows=["rr"], legend={"rr": "#ff0000"})


async def test_draw_ascii_outline_surrounds_art_without_overwriting(call, pixels, tmp_path: Path):
    await new_sprite(call, 5, 5)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    result = await call(
        "draw_ascii",
        path="a.aseprite",
        x=1,
        y=1,
        rows=["rg", "r."],
        legend={"r": "#ff0000", "g": "#00ff00"},
        outline="#0000ff",
    )

    assert await picture(
        pixels, tmp_path / "a.aseprite", 5, 5, {"r": RED, "g": GREEN, "o": BLUE}
    ) == [
        ".oo..",
        "orgo.",
        "oro..",
        ".o...",
        ".....",
    ]
    assert result["painted"] == 10


async def test_draw_ascii_offcanvas_pixels_counted(call, pixels, tmp_path: Path):
    await new_sprite(call, 4, 4)

    result = await call(
        "draw_ascii", path="a.aseprite", x=-1, y=3, rows=["rrr", "rrr"], legend={"r": "#ff0000"}
    )

    assert (result["painted"], result["skipped_outside"]) == (2, 4)
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 3), (1, 3)]) == [RED, RED]


async def test_draw_ascii_unicode_legend_key(call, pixels, tmp_path: Path):
    await new_sprite(call, 4, 4)

    await call(
        "draw_ascii",
        path="a.aseprite",
        x=0,
        y=0,
        rows=["█▓"],
        legend={"█": "#ff0000", "▓": "#0000ff"},
    )

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0)]) == [RED, BLUE]


async def test_draw_ascii_on_indexed_sprite(call, pixels, set_palette, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (0, 0, 255, 255)])

    await call(
        "draw_ascii",
        path="a.aseprite",
        x=0,
        y=0,
        rows=["rb", "bt"],
        legend={"r": "#ff0000", "b": "#0000ff", "t": "transparent"},
    )

    assert await pixels(path, read=[(0, 0), (1, 0), (0, 1), (1, 1)], values=True) == [1, 2, 2, 0]


BOX_COLORS = {"top": "#ff0000", "left": "#00ff00", "right": "#0000ff"}


async def test_isometric_box_exact_pixels(call, pixels, tmp_path: Path):
    await new_sprite(call, 8, 6)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    result = await call(
        "draw_isometric_box", path="a.aseprite", x=4, y=1, w=1, d=1, h=2, **BOX_COLORS
    )

    assert await picture(
        pixels, tmp_path / "a.aseprite", 8, 6, {"T": RED, "L": GREEN, "R": BLUE}
    ) == [
        "........",
        "...TT...",
        "..LTTR..",
        "..LLRR..",
        "...LR...",
        "........",
    ]
    assert result == {"layer": "Layer 1", "frame": 1, "painted": 12, "skipped_outside": 0}


async def test_isometric_box_wider_than_deep(call, pixels, tmp_path: Path):
    await new_sprite(call, 8, 7)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    await call("draw_isometric_box", path="a.aseprite", x=2, y=0, w=2, d=1, h=3, **BOX_COLORS)

    assert await picture(
        pixels, tmp_path / "a.aseprite", 8, 7, {"T": RED, "L": GREEN, "R": BLUE}
    ) == [
        ".TT.....",
        "LTTTT...",
        "LLLTTR..",
        "LLLLRR..",
        ".LLLRR..",
        "...LR...",
        "........",
    ]


async def test_isometric_box_faces_do_not_overlap(call, pixels, grid, tmp_path: Path):
    await new_sprite(call, 16, 16)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    result = await call(
        "draw_isometric_box",
        path="a.aseprite",
        x=7,
        y=1,
        w=3,
        d=2,
        h=4,
        top="#ff000080",
        left="#00ff0080",
        right="#0000ff80",
        blend=True,
    )

    rows = await grid(tmp_path / "a.aseprite")
    assert result["painted"] == "".join(rows).count("#")
    assert all(row.strip(".").count(".") == 0 for row in rows)
    painted = [(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"]
    alphas = {c[3] for c in await pixels(tmp_path / "a.aseprite", read=painted)}
    assert alphas == {128}


async def test_isometric_box_outline(call, pixels, tmp_path: Path):
    await new_sprite(call, 8, 7)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    result = await call(
        "draw_isometric_box",
        path="a.aseprite",
        x=4,
        y=1,
        w=1,
        d=1,
        h=2,
        outline="#ffffff",
        **BOX_COLORS,
    )

    assert await picture(
        pixels,
        tmp_path / "a.aseprite",
        8,
        7,
        {"T": RED, "L": GREEN, "R": BLUE, "o": [255, 255, 255, 255]},
    ) == [
        "...oo...",
        "..oTTo..",
        ".oLTTRo.",
        ".oLLRRo.",
        "..oLRo..",
        "...oo...",
        "........",
    ]
    assert result["painted"] == 24


async def test_isometric_box_limits(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="greater than or equal to 1"):
        await call("draw_isometric_box", path="a.aseprite", x=4, y=0, w=0, d=1, h=2, **BOX_COLORS)
    with pytest.raises(ToolError, match="less than or equal to 128"):
        await call("draw_isometric_box", path="a.aseprite", x=4, y=0, w=1, d=129, h=2, **BOX_COLORS)
    with pytest.raises(ToolError, match="less than or equal to 256"):
        await call("draw_isometric_box", path="a.aseprite", x=4, y=0, w=1, d=1, h=257, **BOX_COLORS)


async def test_isometric_box_without_height_is_only_the_top(call, grid, tmp_path: Path):
    await new_sprite(call, 6, 4)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)

    await call("draw_isometric_box", path="a.aseprite", x=3, y=0, w=1, d=2, h=0, **BOX_COLORS)

    assert await grid(tmp_path / "a.aseprite") == ["..##..", "####..", "##....", "......"]


async def test_pattern_and_shape_tools_refuse_locked_layer(call, locks, tmp_path: Path):
    await new_sprite(call)
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])
    calls = [
        ("draw_gradient", {"rect": rect(0, 0, 4, 4), "colors": ["#000000", "#ffffff"]}),
        (
            "fill_pattern",
            {"rect": rect(0, 0, 4, 4), "color_a": "#000000", "color_b": "#ffffff", "density": 0.5},
        ),
        ("draw_ascii", {"x": 0, "y": 0, "rows": ["r"], "legend": {"r": "#ff0000"}}),
        ("draw_isometric_box", {"x": 4, "y": 0, "w": 1, "d": 1, "h": 1, **BOX_COLORS}),
    ]

    for name, args in calls:
        with pytest.raises(ToolError, match="'Layer 1' is locked; unlock it first"):
            await call(name, path="a.aseprite", **args)


async def test_gradient_pattern_ascii_and_box_in_one_batch(
    call, pixels, tmp_path: Path, monkeypatch
):
    await new_sprite(call, 8, 8)
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
                "tool": "draw_gradient",
                "args": {"rect": rect(0, 0, 8, 1), "colors": ["#ff0000", "#0000ff"]},
            },
            {
                "tool": "fill_pattern",
                "args": {
                    "rect": rect(0, 1, 8, 1),
                    "color_a": "#ff0000",
                    "color_b": "#00ff00",
                    "density": 1,
                },
            },
            {
                "tool": "draw_ascii",
                "args": {"x": 0, "y": 2, "rows": ["b.b"], "legend": {"b": "#0000ff"}},
            },
            {
                "tool": "draw_isometric_box",
                "args": {"x": 4, "y": 4, "w": 1, "d": 1, "h": 0, **BOX_COLORS},
            },
        ],
    )

    assert len(calls) == 1
    assert [r["painted"] for r in result["result"]] == [8, 8, 2, 4]
    assert await pixels(tmp_path / "a.aseprite", read=[(7, 0), (0, 1), (2, 2), (4, 4)]) == [
        BLUE,
        GREEN,
        BLUE,
        RED,
    ]
