import re

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
