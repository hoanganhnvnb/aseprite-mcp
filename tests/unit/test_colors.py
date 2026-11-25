import pytest

from aseprite_mcp.colors import parse_color


def test_parse_rgb_hex_is_opaque():
    assert parse_color("#ff8000") == (255, 128, 0, 255)


def test_parse_rgba_hex():
    assert parse_color("#10203040") == (16, 32, 48, 64)


def test_parse_accepts_uppercase_and_spaces():
    assert parse_color("  #AABBCC ") == (170, 187, 204, 255)


def test_parse_transparent():
    assert parse_color("transparent") == (0, 0, 0, 0)


def test_parse_rejects_missing_hash():
    with pytest.raises(ValueError, match="#RRGGBB"):
        parse_color("ff8000")


def test_parse_rejects_short_hex():
    with pytest.raises(ValueError, match="'#fff'"):
        parse_color("#fff")


def test_parse_rejects_color_names():
    with pytest.raises(ValueError, match="'red'"):
        parse_color("red")


def test_parse_rejects_non_hex_digits():
    with pytest.raises(ValueError):
        parse_color("#gg0000")
