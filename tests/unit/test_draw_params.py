import sys
from pathlib import Path

from aseprite_mcp import colors
from aseprite_mcp.tools._registry import batch_op

SPRITE = Path("a.aseprite")


def test_draw_pixels_sends_pixels_as_one_string():
    pixels = [
        {"x": -3, "y": 1, "color": "#ff000080"},
        {"x": 2, "y": 0, "color": "transparent"},
    ]

    op = batch_op(1, "draw_pixels", {"pixels": pixels}, SPRITE)

    assert op.params["pixels"] == "-3 1 4278190208 2 0 0"


def test_draw_ascii_sends_runs_as_one_string():
    args = {"x": -1, "y": 2, "rows": ["aab"], "legend": {"a": "#ff0000", "b": "#0000ff"}}

    op = batch_op(1, "draw_ascii", args, SPRITE)

    assert op.params["colors"] == [[255, 0, 0, 255], [0, 0, 255, 255]]
    assert op.params["runs"] == "1 2 -1 0 2 2 1 1"


def test_draw_pixels_parses_each_color_once(monkeypatch):
    parsed = []
    parse = colors.parse_color

    def counting(text: str) -> colors.RGBA:
        parsed.append(text)
        return parse(text)

    # Every module that imported parse_color by name, so a builder that parses again counts.
    for name, module in list(sys.modules.items()):
        if name.startswith("aseprite_mcp") and hasattr(module, "parse_color"):
            monkeypatch.setattr(module, "parse_color", counting)
    pixels = [{"x": i, "y": 0, "color": "#102030"} for i in range(50)]

    batch_op(1, "draw_pixels", {"pixels": pixels}, SPRITE)

    assert len(parsed) == 50
