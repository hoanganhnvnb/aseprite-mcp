import warnings

import pytest
from PIL import Image

from aseprite_mcp import sheet
from aseprite_mcp.errors import ToolError
from aseprite_mcp.tools._registry import BATCHABLE, batch_op
from aseprite_mcp.tools.read import ROW_CHARS, format_pixels


def rgba_value(r: int, g: int, b: int, a: int) -> int:
    return a << 24 | b << 16 | g << 8 | r


def test_format_rows_names_colours_in_order_of_appearance():
    pixels = [rgba_value(0, 0, 255, 255), 0, rgba_value(255, 0, 0, 255), rgba_value(0, 0, 255, 255)]

    rows = format_pixels({"x": 1, "y": 2, "w": 2, "h": 2, "pixels": pixels}, "rows")

    assert rows == {
        "x": 1,
        "y": 2,
        "w": 2,
        "h": 2,
        "rows": ["A.", "BA"],
        "legend": {"A": "#0000ff", "B": "#ff0000"},
    }


def test_format_rows_treats_any_zero_alpha_as_transparent():
    result = format_pixels({"x": 0, "y": 0, "w": 1, "h": 1, "pixels": [0x00FFFFFF]}, "json")

    assert result["pixels"] == [["transparent"]]


def test_format_rows_runs_out_of_characters():
    count = len(ROW_CHARS) + 1
    data = {"x": 0, "y": 0, "w": count, "h": 1, "pixels": [0xFF000000 | i for i in range(count)]}

    with pytest.raises(ToolError, match="format='hex'"):
        format_pixels(data, "rows")


def test_row_chars_never_include_untouched_marks():
    assert "." not in ROW_CHARS
    assert " " not in ROW_CHARS
    assert len(set(ROW_CHARS)) == len(ROW_CHARS)


def test_read_tools_are_batchable_and_view_sprite_is_not():
    assert BATCHABLE["read_pixels"][:2] == ("read_pixels", False)
    assert BATCHABLE["get_bounds"][:2] == ("get_bounds", False)
    assert BATCHABLE["compare_frames"][:2] == ("compare_frames", False)
    assert BATCHABLE["get_color_stats"][:2] == ("get_color_stats", False)
    assert BATCHABLE["find_stray_pixels"][:2] == ("find_stray_pixels", False)
    assert "view_sprite" not in BATCHABLE


def test_read_pixels_limit_checked_when_batched(tmp_path):
    args = {"rect": {"x": 0, "y": 0, "w": 300, "h": 300}}

    with pytest.raises(ToolError, match="op 1 \\(read_pixels\\): .*90000 pixels"):
        batch_op(1, "read_pixels", args, tmp_path / "a.aseprite")


def test_read_tool_args_build_without_warnings(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        op = batch_op(1, "get_bounds", {"frames": "1-3"}, tmp_path / "a.aseprite")

    assert op.params == {"layer": None, "frames": [1, 2, 3]}


def test_sheet_default_scale_fits_512():
    layout = sheet.plan(16, 8, count=1, scale=None)

    assert (layout.scale, layout.shrink) == (32, 1)
    assert layout.size == (512, 256)
    assert layout.notes == []


def test_sheet_default_scale_is_at_least_one():
    layout = sheet.plan(1000, 10, count=1, scale=None)

    assert (layout.scale, layout.shrink) == (1, 1)


def test_sheet_reduces_a_scale_over_the_cap():
    layout = sheet.plan(600, 10, count=1, scale=8)

    assert layout.scale == 3
    assert layout.size == (1800, 30)
    assert layout.notes == ["requested scale 8 would make the image 4800 px wide; reduced to 3"]


def test_sheet_shrinks_when_scale_one_is_too_big():
    layout = sheet.plan(4096, 30, count=1, scale=None)

    assert (layout.scale, layout.shrink) == (1, 2)
    assert layout.size == (2048, 15)
    assert "1/2" in layout.notes[0]


def test_sheet_says_a_requested_scale_was_dropped_when_shrinking():
    layout = sheet.plan(4096, 30, count=1, scale=4)

    assert layout.shrink == 2
    assert layout.notes[0] == "requested scale 4 does not fit 2048 px; reduced"
    assert "one pixel out of 2 in each direction" in layout.notes[1]


def test_sheet_lays_frames_out_in_a_square_grid():
    layout = sheet.plan(4, 4, count=6, scale=1)

    assert (layout.columns, layout.rows) == (3, 2)
    assert layout.size == (3 * 4 + 2 * sheet.GAP, 2 * 4 + sheet.GAP)


def test_sheet_grid_lines_need_scale_4():
    frame = Image.new("RGBA", (2, 2), (255, 255, 255, 255))

    _, layout = sheet.render([frame], origin=(0, 0), scale=2, grid=True)

    assert layout.notes == ["grid needs scale 4 or more; left out"]


def test_sheet_onion_skin_fades_older_frames():
    old = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
    current = Image.new("RGBA", (1, 1), (0, 0, 0, 0))

    merged = sheet.onion([old], current)

    assert merged.getpixel((0, 0)) == (255, 0, 0, 128)
