import os
import shutil
import sys
from pathlib import Path

import pytest
from PIL import ImageFont

from aseprite_mcp import fonts
from aseprite_mcp.config import Settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.fonts import FontEntry, find_font, font_dirs, load_font, render_text, scan_fonts

WHITE = (255, 255, 255, 255)
RED = (255, 0, 0, 255)
BLACK = (0, 0, 0, 255)


def some_font() -> FontEntry:
    found = fonts.installed_fonts(font_dirs(sys.platform, os.environ))
    if not found:
        pytest.skip("no TrueType/OpenType font installed")
    return found[0]


def settings(root: Path, sandbox: bool) -> Settings:
    return Settings(
        aseprite=None,
        root=root,
        sandbox=sandbox,
        timeout=60.0,
        max_procs=1,
        allow_lua=False,
        max_read_pixels=65536,
    )


def entry(family: str, style: str, name: str) -> FontEntry:
    return FontEntry(family=family, style=style, path=Path(f"/fonts/{name}"))


def default_font(size: int = 16):
    return load_font(None, size)


def test_font_dirs_linux_defaults():
    home = Path("/home/u")

    assert font_dirs("linux", {}, home) == [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path("/home/u/.local/share/fonts"),
        Path("/home/u/.fonts"),
    ]


def test_font_dirs_windows_uses_env_variables():
    env = {"WINDIR": "D:/Win", "LOCALAPPDATA": "D:/Users/u/AppData/Local"}

    assert font_dirs("win32", env, Path("D:/Users/u")) == [
        Path("D:/Win/Fonts"),
        Path("D:/Users/u/AppData/Local/Microsoft/Windows/Fonts"),
    ]


def test_font_dirs_windows_without_env_has_no_dirs():
    assert font_dirs("win32", {}, Path("D:/Users/u")) == []


def test_font_dirs_macos_defaults():
    assert font_dirs("darwin", {}, Path("/Users/u")) == [
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
        Path("/Users/u/Library/Fonts"),
    ]


def test_font_dirs_adds_env_override_split_by_pathsep():
    env = {"ASEPRITE_MCP_FONT_DIRS": os.pathsep.join(["/extra/a", "", "/extra/b"])}

    dirs = font_dirs("linux", env, Path("/home/u"))

    assert dirs[:2] == [Path("/extra/a"), Path("/extra/b")]
    assert Path("/usr/share/fonts") in dirs


def test_scan_finds_fonts_in_nested_directories(tmp_path):
    real = some_font()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    shutil.copy(real.path, nested / f"copy{real.path.suffix}")

    found = scan_fonts([tmp_path])

    assert found
    assert {f.path for f in found} == {nested / f"copy{real.path.suffix}"}
    assert found[0].family == real.family


def test_font_dirs_expands_tilde_with_given_home():
    env = {"ASEPRITE_MCP_FONT_DIRS": os.pathsep.join(["~/myfonts", "~"])}

    assert font_dirs("linux", env, Path("/home/u"))[:2] == [
        Path("/home/u/myfonts"),
        Path("/home/u"),
    ]


def test_scan_lists_a_font_once_when_dirs_overlap(tmp_path):
    real = some_font()
    inner = tmp_path / "inner"
    inner.mkdir()
    shutil.copy(real.path, inner / f"copy{real.path.suffix}")

    found = scan_fonts([inner, tmp_path])

    assert len(found) == len(scan_fonts([inner]))
    assert len({(f.name, f.index) for f in found}) == len(found)
    assert {f.path for f in found} == {inner / f"copy{real.path.suffix}"}


def test_scan_lists_a_symlinked_font_once(tmp_path):
    real = some_font()
    shutil.copy(real.path, tmp_path / f"a{real.path.suffix}")
    (tmp_path / f"b{real.path.suffix}").symlink_to(tmp_path / f"a{real.path.suffix}")

    found = scan_fonts([tmp_path])

    assert {f.path.name for f in found} == {f"a{real.path.suffix}"}


def test_scan_skips_files_that_are_not_fonts(tmp_path):
    (tmp_path / "broken.ttf").write_bytes(b"not a font at all")
    (tmp_path / "empty.otf").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "dangling.ttf").symlink_to(tmp_path / "missing.ttf")

    assert scan_fonts([tmp_path]) == []


def test_scan_tolerates_missing_and_unreadable_dirs(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "x.ttf").write_bytes(b"junk")
    locked.chmod(0)
    try:
        assert scan_fonts([tmp_path / "missing", locked, tmp_path / "file.ttf"]) == []
    finally:
        locked.chmod(0o755)


def test_installed_fonts_rescans_after_a_font_is_added(tmp_path):
    real = some_font()
    assert fonts.installed_fonts([tmp_path]) == []

    shutil.copy(real.path, tmp_path / f"new{real.path.suffix}")

    assert len(fonts.installed_fonts([tmp_path])) >= 1


def test_find_font_is_case_insensitive_and_offers_suggestions():
    entries = [
        entry("Pixel Sans", "Regular", "PixelSans.ttf"),
        entry("Pixel Sans", "Bold", "PixelSans-Bold.ttf"),
        entry("Serif Book", "Regular", "SerifBook.otf"),
    ]

    assert find_font("pixel sans", entries).style == "Regular"
    assert find_font("PIXEL SANS BOLD", entries).style == "Bold"
    assert find_font("pixelsans-bold", entries).style == "Bold"
    with pytest.raises(ToolError, match="Pixel Sans.*list_fonts"):
        find_font("Pixle Sans", entries)


def test_find_font_by_path_respects_sandbox(tmp_path):
    real = some_font()
    root = tmp_path / "root"
    root.mkdir()
    inside = root / f"inside{real.path.suffix}"
    outside = tmp_path / f"outside{real.path.suffix}"
    shutil.copy(real.path, inside)
    shutil.copy(real.path, outside)
    sandboxed = settings(root, sandbox=True)

    assert find_font(str(inside), [], sandboxed).path == inside
    with pytest.raises(ToolError, match="outside the allowed root"):
        find_font(str(outside), [], sandboxed)


def test_find_font_by_path_rejects_other_extensions(tmp_path):
    picture = tmp_path / "picture.png"
    picture.write_bytes(b"x")

    with pytest.raises(ToolError, match="not a font file"):
        find_font(str(picture), [], settings(tmp_path, sandbox=False))


def test_render_text_without_antialias_has_only_two_alpha_values():
    image = render_text("Hello", default_font(), RED)

    assert image.mode == "RGBA"
    assert set(image.getchannel("A").tobytes()) == {0, 255}
    assert {px for _, px in image.getcolors() if px[3]} == {RED}


def test_antialias_keeps_partial_alpha():
    image = render_text("Hello", default_font(), RED, antialias=True)

    alphas = set(image.getchannel("A").tobytes())
    assert any(0 < a < 255 for a in alphas)


def test_render_text_is_cropped_to_the_ink():
    image = render_text("Hi", default_font(), RED)

    assert image.getchannel("A").getbbox() == (0, 0, *image.size)


def test_render_text_outline_and_shadow_grow_the_image():
    font = default_font()
    plain = render_text("Hi", font, RED)
    outlined = render_text("Hi", font, RED, outline=BLACK, outline_width=2)
    shadowed = render_text("Hi", font, RED, shadow=BLACK, shadow_dx=3, shadow_dy=1)

    assert outlined.size == (plain.width + 4, plain.height + 4)
    assert shadowed.size == (plain.width + 3, plain.height + 1)
    assert BLACK in {px for _, px in outlined.getcolors()}


def test_outline_is_four_neighbour():
    image = render_text("I", default_font(32), RED, outline=BLACK, outline_width=3)

    assert image.getpixel((0, 0)) == (0, 0, 0, 0)


def test_bold_is_one_pixel_wider():
    font = default_font()

    assert render_text("l", font, RED, bold=True).width == render_text("l", font, RED).width + 1


def test_text_too_large_rejected():
    with pytest.raises(ToolError, match="2048"):
        render_text("W" * 400, default_font(256), RED)


def test_text_longer_than_2000_characters_rejected():
    with pytest.raises(ToolError, match="2000"):
        render_text("a" * 2001, default_font(8), RED)


def test_load_font_rejects_size_over_256():
    with pytest.raises(ToolError, match="256"):
        load_font(None, 257)


def test_default_font_fallback_when_no_fonts(tmp_path):
    assert scan_fonts([tmp_path]) == []

    font = load_font(None, 12)

    assert isinstance(font, ImageFont.FreeTypeFont | ImageFont.ImageFont)
    assert render_text("ok", font, RED).width > 0


def test_letter_spacing_widens_text():
    font = default_font()
    narrow = render_text("abcd", font, RED, letter_spacing=1)

    wide = render_text("abcd", font, RED, letter_spacing=4)

    assert wide.width == narrow.width + 9


def test_multiline_height():
    font = default_font()
    one = render_text("H", font, RED)

    two = render_text("H\nH", font, RED, line_spacing=5)

    ascent, descent = font.getmetrics()
    assert two.height == one.height + ascent + descent + 5


def test_whitespace_only_text_is_empty():
    assert render_text("  \n ", default_font(), RED).size == (0, 0)


def test_crlf_line_breaks_render_like_newlines():
    font = default_font()

    assert render_text("a\r\nb", font, RED).size == render_text("a\nb", font, RED).size


def test_lone_carriage_return_is_a_line_break():
    font = default_font()

    assert render_text("a\rb", font, RED).size == render_text("a\nb", font, RED).size


def test_length_limit_counts_crlf_as_one_character():
    font = default_font(1)

    image = render_text("a\r\n" * 999 + "a", font, RED)

    assert image.size == render_text("a\n" * 999 + "a", font, RED).size
