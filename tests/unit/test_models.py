import pytest
from pydantic import ValidationError

from aseprite_mcp.models import Pixel, Point


def test_point_accepts_negative_coordinates():
    assert Point(x=-3, y=7) == Point.model_validate({"x": -3, "y": 7})


def test_point_rejects_numeric_strings():
    with pytest.raises(ValidationError, match="valid integer"):
        Point.model_validate({"x": "3", "y": 0})


def test_point_rejects_floats():
    with pytest.raises(ValidationError, match="valid integer"):
        Point.model_validate({"x": 1.5, "y": 0})


def test_point_rejects_far_coordinates():
    with pytest.raises(ValidationError, match="less than or equal to 65535"):
        Point.model_validate({"x": 70000, "y": 0})


def test_pixel_checks_color():
    with pytest.raises(ValidationError, match="'#RRGGBB'"):
        Pixel.model_validate({"x": 0, "y": 0, "color": "red"})


def test_pixel_keeps_color_text():
    assert Pixel.model_validate({"x": 0, "y": 0, "color": "#ff000080"}).color == "#ff000080"
