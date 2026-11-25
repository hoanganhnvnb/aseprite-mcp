import re
from itertools import pairwise
from typing import Literal

RGBA = tuple[int, int, int, int]

_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})")


def parse_color(s: str) -> RGBA:
    text = s.strip()
    if text.lower() == "transparent":
        return (0, 0, 0, 0)
    match = _HEX.fullmatch(text)
    if match is None:
        raise ValueError(f"Invalid color {s!r}: use '#RRGGBB', '#RRGGBBAA' or 'transparent'")
    digits = match.group(1)
    if len(digits) == 6:
        digits += "ff"
    r, g, b, a = (int(digits[i : i + 2], 16) for i in range(0, 8, 2))
    return (r, g, b, a)


def to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Hue in degrees [0, 360), saturation and lightness in [0, 1]."""
    rf, gf, bf = r / 255, g / 255, b / 255
    hi, lo = max(rf, gf, bf), min(rf, gf, bf)
    light = (hi + lo) / 2
    if hi == lo:
        return 0.0, 0.0, light
    span = hi - lo
    sat = min(1.0, span / (1 - abs(2 * light - 1)))
    if hi == rf:
        hue = ((gf - bf) / span) % 6
    elif hi == gf:
        hue = (bf - rf) / span + 2
    else:
        hue = (rf - gf) / span + 4
    return hue * 60 % 360, sat, light


def hsl_to_rgb(hue: float, sat: float, light: float) -> tuple[int, int, int]:
    chroma = (1 - abs(2 * light - 1)) * sat
    sector = (hue % 360) / 60
    x = chroma * (1 - abs(sector % 2 - 1))
    r, g, b = [
        (chroma, x, 0.0),
        (x, chroma, 0.0),
        (0.0, chroma, x),
        (0.0, x, chroma),
        (x, 0.0, chroma),
        (chroma, 0.0, x),
    ][int(sector) % 6]
    m = light - chroma / 2
    r8, g8, b8 = (min(255, max(0, round((v + m) * 255))) for v in (r, g, b))
    return r8, g8, b8


WARM_HUE = 60.0
COOL_HUE = 240.0


def _turn(hue: float, target: float, degrees: float) -> float:
    """Turn hue towards target by at most `degrees`, the short way round."""
    diff = (target - hue + 180) % 360 - 180
    return (hue + max(-degrees, min(degrees, diff))) % 360


def generate_ramp(
    base: str,
    steps: int,
    hue_shift: float = 0.0,
    lightness_range: tuple[float, float] = (0.1, 0.9),
) -> list[str]:
    """A dark-to-light ramp of `steps` colours that contains the base colour.

    The base sits where its lightness falls in lightness_range (which is widened to
    reach it); the other steps are evenly spaced in lightness on either side. Each
    step away from the base turns the hue by hue_shift degrees, darker steps towards
    blue and lighter ones towards yellow, never past them.
    """
    lo, hi = lightness_range
    if not 0 <= lo < hi <= 1:
        raise ValueError(f"lightness_range {lightness_range} must rise within 0..1")
    r, g, b, _ = parse_color(base)
    hue, sat, light = rgb_to_hsl(r, g, b)
    lo, hi = min(lo, light), max(hi, light)
    at = round((light - lo) / (hi - lo) * (steps - 1))
    ramp = []
    for i in range(steps):
        if i == at:
            ramp.append(to_hex(r, g, b))
            continue
        if i < at:
            level = lo + (light - lo) * i / at
            turned = _turn(hue, COOL_HUE, hue_shift * (at - i))
        else:
            level = light + (hi - light) * (i - at) / (steps - 1 - at)
            turned = _turn(hue, WARM_HUE, hue_shift * (i - at))
        ramp.append(to_hex(*hsl_to_rgb(turned, sat, level)))
    lights = [sum(sorted(parse_color(c)[:3])[::2]) for c in ramp]
    if any(a >= b for a, b in pairwise(lights)):
        raise ValueError(f"lightness_range {lightness_range} is too narrow for {steps} steps")
    return ramp


# Well-known public palettes, in the order their authors publish them.
PALETTES: dict[str, list[str]] = {
    "pico8": [
        "#000000", "#1d2b53", "#7e2553", "#008751", "#ab5236", "#5f574f", "#c2c3c7", "#fff1e8",
        "#ff004d", "#ffa300", "#ffec27", "#00e436", "#29adff", "#83769c", "#ff77a8", "#ffccaa",
    ],
    "gameboy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "db16": [
        "#140c1c", "#442434", "#30346d", "#4e4a4e", "#854c30", "#346524", "#d04648", "#757161",
        "#597dce", "#d27d2c", "#8595a1", "#6daa2c", "#d2aa99", "#6dc2ca", "#dad45e", "#deeed6",
    ],
    "db32": [
        "#000000", "#222034", "#45283c", "#663931", "#8f563b", "#df7126", "#d9a066", "#eec39a",
        "#fbf236", "#99e550", "#6abe30", "#37946e", "#4b692f", "#524b24", "#323c39", "#3f3f74",
        "#306082", "#5b6ee1", "#639bff", "#5fcde4", "#cbdbfc", "#ffffff", "#9badb7", "#847e87",
        "#696a6a", "#595652", "#76428a", "#ac3232", "#d95763", "#d77bba", "#8f974a", "#8a6f30",
    ],
    "sweetie16": [
        "#1a1c2c", "#5d275d", "#b13e53", "#ef7d57", "#ffcd75", "#a7f070", "#38b764", "#257179",
        "#29366f", "#3b5dc9", "#41a6f6", "#73eff7", "#f4f4f4", "#94b0c2", "#566c86", "#333c57",
    ],
    "endesga32": [
        "#be4a2f", "#d77643", "#ead4aa", "#e4a672", "#b86f50", "#733e39", "#3e2731", "#a22633",
        "#e43b44", "#f77622", "#feae34", "#fee761", "#63c74d", "#3e8948", "#265c42", "#193c3e",
        "#124e89", "#0099db", "#2ce8f5", "#ffffff", "#c0cbdc", "#8b9bb4", "#5a6988", "#3a4466",
        "#262b44", "#181425", "#ff0044", "#68386c", "#b55088", "#f6757a", "#e8b796", "#c28569",
    ],
    # The NES 2C02 palette as most pixel-art tools ship it, repeated blacks removed.
    "nes": [
        "#7c7c7c", "#0000fc", "#0000bc", "#4428bc", "#940084", "#a80020", "#a81000", "#881400",
        "#503000", "#007800", "#006800", "#005800", "#004058", "#000000",
        "#bcbcbc", "#0078f8", "#0058f8", "#6844fc", "#d800cc", "#e40058", "#f83800", "#e45c10",
        "#ac7c00", "#00b800", "#00a800", "#00a844", "#008888",
        "#f8f8f8", "#3cbcfc", "#6888fc", "#9878f8", "#f878f8", "#f85898", "#f87858", "#fca044",
        "#f8b800", "#b8f818", "#58d854", "#58f898", "#00e8d8", "#787878",
        "#fcfcfc", "#a4e4fc", "#b8b8f8", "#d8b8f8", "#f8b8f8", "#f8a4c0", "#f0d0b0", "#fce0a8",
        "#f8d878", "#d8f878", "#b8f8b8", "#b8f8d8", "#00fcfc", "#f8d8f8",
    ],
}  # fmt: skip

PaletteName = Literal[tuple(PALETTES)]  # type: ignore[valid-type]
