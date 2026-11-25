from typing import get_args

import pytest

from aseprite_mcp.colors import (
    PALETTES,
    PaletteName,
    generate_ramp,
    hsl_to_rgb,
    parse_color,
    rgb_to_hsl,
)


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


def lightness(color: str) -> float:
    r, g, b, _ = parse_color(color)
    return (max(r, g, b) + min(r, g, b)) / 2


def test_ramp_steps_and_order():
    ramp = generate_ramp("#3f7fbf", steps=6)

    assert len(ramp) == 6
    assert "#3f7fbf" in ramp
    lights = [lightness(c) for c in ramp]
    assert lights == sorted(set(lights))


def test_ramp_of_gray_spans_the_lightness_range():
    assert generate_ramp("#808080", steps=3, lightness_range=(0.1, 0.9)) == [
        "#1a1a1a",
        "#808080",
        "#e6e6e6",
    ]


def test_ramp_starts_at_a_base_near_the_dark_end():
    ramp = generate_ramp("#202020", steps=5, lightness_range=(0.1, 0.9))

    assert ramp[0] == "#202020"
    assert ramp[-1] == "#e6e6e6"


def test_ramp_extends_the_range_to_reach_the_base():
    ramp = generate_ramp("#ffffff", steps=3, lightness_range=(0.2, 0.8))

    assert ramp[-1] == "#ffffff"


def test_ramp_hue_shift_turns_shadows_cool_and_highlights_warm():
    ramp = generate_ramp("#bf4040", steps=3, hue_shift=20)

    assert ramp[1] == "#bf4040"
    # red has hue 0: shadows turn towards blue (240), highlights towards yellow (60)
    assert rgb_to_hsl(*parse_color(ramp[0])[:3])[0] == pytest.approx(340, abs=3)
    assert rgb_to_hsl(*parse_color(ramp[2])[:3])[0] == pytest.approx(20, abs=3)


def test_ramp_hue_shift_stops_at_the_target_hue():
    ramp = generate_ramp("#4040bf", steps=5, hue_shift=60)

    assert rgb_to_hsl(*parse_color(ramp[0])[:3])[0] == pytest.approx(240, abs=1)


def test_ramp_rejects_reversed_lightness_range():
    with pytest.raises(ValueError, match="lightness_range"):
        generate_ramp("#808080", steps=4, lightness_range=(0.8, 0.2))


def test_hsl_round_trip():
    assert hsl_to_rgb(*rgb_to_hsl(200, 100, 50)) == (200, 100, 50)


def test_preset_sizes():
    assert len(PALETTES["pico8"]) == 16
    assert len(PALETTES["gameboy"]) == 4
    assert len(PALETTES["db16"]) == 16
    assert len(PALETTES["db32"]) == 32
    assert len(PALETTES["nes"]) == 55


def test_preset_colours_are_opaque_hex_without_duplicates():
    for name, colors in PALETTES.items():
        assert len(set(colors)) == len(colors), name
        for color in colors:
            assert len(color) == 7, (name, color)
            assert parse_color(color)[3] == 255


def test_pico8_starts_black_and_ends_peach():
    assert PALETTES["pico8"][0] == "#000000"
    assert PALETTES["pico8"][-1] == "#ffccaa"


def test_palette_name_literal_matches_presets():
    assert get_args(PaletteName) == tuple(PALETTES)
