import os
import shutil
import sys
from pathlib import Path

import pytest

from aseprite_mcp import fonts, ops
from aseprite_mcp.errors import ToolError

RED = [255, 0, 0, 255]
BLACK = [0, 0, 0, 255]
CLEAR = [0, 0, 0, 0]


async def new_sprite(call, w: int = 32, h: int = 24, **args) -> None:
    await call("create_sprite", path="a.aseprite", width=w, height=h, **args)


async def canvas(pixels, path: Path, w: int, h: int, **args) -> dict:
    coords = [(x, y) for y in range(h) for x in range(w)]
    found = await pixels(path, read=coords, **args)
    return {xy: tuple(c) for xy, c in zip(coords, found) if c[3] > 0}


def bounds(painted) -> tuple[int, int, int, int]:
    xs = [x for x, _ in painted]
    ys = [y for _, y in painted]
    return min(xs), min(ys), max(xs), max(ys)


async def no_aseprite(*args, **kwargs):
    raise AssertionError("Aseprite should not run")


async def test_draw_text_paints_pixels_with_given_colour(call, pixels, tmp_path: Path):
    await new_sprite(call)

    result = await call("draw_text", path="a.aseprite", text="Hi", x=2, y=3, color="#ff0000")

    painted = await canvas(pixels, tmp_path / "a.aseprite", 32, 24)
    assert set(painted.values()) == {tuple(RED)}
    assert len(painted) == result["painted"]
    assert bounds(painted) == (2, 3, 2 + result["width"] - 1, 3 + result["height"] - 1)
    assert result["skipped_outside"] == 0
    assert (result["layer"], result["frame"]) == ("Layer 1", 1)


async def test_draw_text_anchor_center_is_centred_on_point(call, grid, tmp_path: Path):
    await new_sprite(call)
    size = await call("measure_text", text="Hi")

    await call(
        "draw_text", path="a.aseprite", text="Hi", x=16, y=12, color="#ff0000", anchor="center"
    )

    rows = await grid(tmp_path / "a.aseprite")
    painted = [(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"]
    left, top, right, bottom = bounds(painted)
    assert (left, top) == (16 - (size["width"] - 1) // 2, 12 - (size["height"] - 1) // 2)
    assert (right - left + 1, bottom - top + 1) == (size["width"], size["height"])


async def test_draw_text_anchor_bottom_right_puts_last_pixel_on_point(call, grid, tmp_path: Path):
    await new_sprite(call)

    await call(
        "draw_text",
        path="a.aseprite",
        text="Hi",
        x=30,
        y=20,
        color="#ff0000",
        anchor="bottom_right",
    )

    rows = await grid(tmp_path / "a.aseprite")
    painted = [(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"]
    assert bounds(painted)[2:] == (30, 20)


async def test_draw_text_outline_has_outline_colour(call, pixels, tmp_path: Path):
    await new_sprite(call)

    result = await call(
        "draw_text",
        path="a.aseprite",
        text="Hi",
        x=2,
        y=2,
        color="#ff0000",
        outline="#000000",
    )

    painted = await canvas(pixels, tmp_path / "a.aseprite", 32, 24)
    assert set(painted.values()) == {tuple(RED), tuple(BLACK)}
    left, top, _, _ = bounds(painted)
    assert (left, top) == (2, 2)
    leftmost = [painted[(x, y)] for x, y in painted if x == 2]
    assert set(leftmost) == {tuple(BLACK)}
    assert len(painted) == result["painted"]


async def test_draw_text_clips_at_canvas_edge_and_counts_skipped(call, pixels, tmp_path: Path):
    await new_sprite(call, 8, 24)
    size = await call("measure_text", text="Hi")

    result = await call("draw_text", path="a.aseprite", text="Hi", x=4, y=2, color="#ff0000")

    painted = await canvas(pixels, tmp_path / "a.aseprite", 8, 24)
    assert len(painted) == result["painted"] > 0
    assert result["skipped_outside"] > 0
    assert max(x for x, _ in painted) == 7
    assert size["width"] > 4


async def test_draw_text_far_off_canvas_paints_nothing(call, tmp_path: Path):
    await new_sprite(call, 8, 8)

    result = await call("draw_text", path="a.aseprite", text="Hi", x=-500, y=0, color="#ff0000")

    assert result["painted"] == 0
    assert result["skipped_outside"] > 0


async def test_draw_text_on_indexed_sprite(call, pixels, set_palette, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 24, 20, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (0, 0, 0, 255), (250, 10, 10, 255), (0, 0, 255, 255)])

    await call("draw_text", path="a.aseprite", text="Hi", x=1, y=1, color="#ff0000")

    coords = [(x, y) for y in range(20) for x in range(24)]
    values = await pixels(path, read=coords, values=True)
    assert set(values) == {0, 2}


async def test_draw_text_antialias_without_blend_keeps_partial_alpha(call, pixels, tmp_path: Path):
    await new_sprite(call)

    await call("draw_text", path="a.aseprite", text="Hi", x=1, y=1, color="#ff0000", antialias=True)

    painted = await canvas(pixels, tmp_path / "a.aseprite", 32, 24)
    assert {c[:3] for c in painted.values()} == {(255, 0, 0)}
    assert any(c[3] < 255 for c in painted.values())


async def test_draw_text_antialias_with_blend_mixes_with_what_is_there(
    call, pixels, tmp_path: Path
):
    await new_sprite(call)
    await call(
        "draw_rect",
        path="a.aseprite",
        rect={"x": 0, "y": 0, "w": 32, "h": 24},
        color="#0000ff",
        fill=True,
    )

    await call(
        "draw_text",
        path="a.aseprite",
        text="Hi",
        x=1,
        y=1,
        color="#ff0000",
        antialias=True,
        blend=True,
    )

    painted = await canvas(pixels, tmp_path / "a.aseprite", 32, 24)
    assert {c[3] for c in painted.values()} == {255}
    assert any(0 < c[0] < 255 and 0 < c[2] < 255 for c in painted.values())


async def test_draw_text_refuses_locked_layer(call, locks, tmp_path: Path):
    await new_sprite(call)
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked; unlock it first"):
        await call("draw_text", path="a.aseprite", text="Hi", x=0, y=0, color="#ff0000")


async def test_draw_text_linked_cel_untouched_in_other_frames(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await pixels(path, put=[(0, 0, *BLACK)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2", link=True)

    await call("draw_text", path="a.aseprite", text="Hi", x=2, y=2, color="#ff0000", frame=2)

    assert await canvas(pixels, path, 32, 24, frame=1) == {(0, 0): tuple(BLACK)}
    assert len(await canvas(pixels, path, 32, 24, frame=2)) > 1
    first, second = await cels(path)
    assert first["image_id"] != second["image_id"]


async def test_measure_text_matches_drawn_size(call, tmp_path: Path):
    await new_sprite(call, 64, 48)

    size = await call("measure_text", text="Hi\nthere", outline_width=1, shadow_dx=2, shadow_dy=2)
    result = await call(
        "draw_text",
        path="a.aseprite",
        text="Hi\nthere",
        x=1,
        y=1,
        color="#ff0000",
        outline="#000000",
        shadow="#00ff00",
        shadow_dx=2,
        shadow_dy=2,
    )

    assert size["lines"] == 2
    assert (size["width"], size["height"]) == (result["width"], result["height"])


async def test_list_fonts_filters_by_query(call, tmp_path: Path, monkeypatch):
    installed = fonts.installed_fonts(fonts.font_dirs(sys.platform, os.environ))
    if not installed:
        pytest.skip("no TrueType/OpenType font installed")
    extra = tmp_path / "extra"
    extra.mkdir()
    shutil.copy(installed[0].path, extra / f"zzqfont{installed[0].path.suffix}")
    monkeypatch.setenv("ASEPRITE_MCP_FONT_DIRS", str(extra))

    found = await call("list_fonts", query="ZZQ")
    nothing = await call("list_fonts", query="no such font name zzz")

    assert found["total"] >= 1
    assert all("zzq" in Path(f["path"]).name for f in found["fonts"])
    assert str(extra) in found["dirs"]
    assert (nothing["total"], nothing["fonts"]) == (0, [])


async def test_draw_text_with_font_from_list(call, grid, tmp_path: Path):
    installed = fonts.installed_fonts(fonts.font_dirs(sys.platform, os.environ))
    if not installed:
        pytest.skip("no TrueType/OpenType font installed")
    await new_sprite(call)

    result = await call(
        "draw_text", path="a.aseprite", text="Hi", x=1, y=1, color="#ff0000", font=installed[0].name
    )

    assert result["painted"] > 0


async def test_draw_text_unknown_font_suggests_list_fonts(call, monkeypatch, tmp_path: Path):
    await new_sprite(call)
    monkeypatch.setattr(ops, "run_script", no_aseprite)

    with pytest.raises(ToolError, match="list_fonts"):
        await call(
            "draw_text",
            path="a.aseprite",
            text="Hi",
            x=0,
            y=0,
            color="#ff0000",
            font="No Such Font Qwerty",
        )


async def test_draw_text_in_batch(call, pixels, tmp_path: Path, monkeypatch):
    await new_sprite(call)
    runs = []
    real_run_script = ops.run_script

    async def counting_run_script(*args, **kwargs):
        runs.append(args[0])
        return await real_run_script(*args, **kwargs)

    monkeypatch.setattr(ops, "run_script", counting_run_script)

    result = await call(
        "batch",
        path="a.aseprite",
        ops=[
            {"tool": "draw_text", "args": {"text": "A", "x": 1, "y": 1, "color": "#ff0000"}},
            {"tool": "draw_text", "args": {"text": "B", "x": 16, "y": 1, "color": "#000000"}},
        ],
    )

    assert len(runs) == 1
    assert all(r["painted"] > 0 for r in result["result"])
    painted = await canvas(pixels, tmp_path / "a.aseprite", 32, 24)
    assert set(painted.values()) == {tuple(RED), tuple(BLACK)}


async def test_draw_text_too_large_fails_before_aseprite(call, monkeypatch, tmp_path: Path):
    await new_sprite(call)
    monkeypatch.setattr(ops, "run_script", no_aseprite)

    with pytest.raises(ToolError, match="2048"):
        await call(
            "draw_text", path="a.aseprite", text="W" * 400, x=0, y=0, color="#ff0000", size=256
        )


async def test_draw_text_blank_text_paints_nothing(call, tmp_path: Path):
    await new_sprite(call, 8, 8)

    result = await call("draw_text", path="a.aseprite", text=" \n ", x=0, y=0, color="#ff0000")

    assert (result["painted"], result["width"], result["height"]) == (0, 0, 0)
