from pathlib import Path

import pytest
from PIL import Image

from aseprite_mcp import fonts, server, sheet_fonts
from aseprite_mcp.errors import ToolError
from aseprite_mcp.fonts import FontEntry, find_font, render_text
from aseprite_mcp.sheet_fonts import install_dirs, load_sheet, read_fonts_xml

KEY = (255, 255, 255, 255)
INK = (0, 0, 0, 255)
RED = (255, 0, 0, 255)

GLYPHS = {
    " ": ["...", "...", "...", "..."],
    "A": [".#..", "#.#.", "###.", "#.#."],
    "B": ["##..", "###.", "#.#.", "###."],
    "\x80": ["###.", "#.#.", "#.#.", "###."],
}


def make_sheet(path: Path, glyphs: dict[str, list[str]] = GLYPHS, last: int = 128) -> None:
    """A sheet laid out like Aseprite's: white key colour, one glyph box per code point
    from 32 on, 16 boxes per row; code points without a picture get a red-marked box."""
    height = 4
    boxes = []
    for code in range(32, last + 1):
        rows = glyphs.get(chr(code))
        boxes.append(rows if rows else ["R"] * height)
    width = 1 + 16 * 5
    sheet = Image.new("RGBA", (width, 1 + (len(boxes) + 15) // 16 * (height + 1)), KEY)
    for i, rows in enumerate(boxes):
        left, top = 1 + (i % 16) * 5, 1 + (i // 16) * (height + 1)
        for dy, row in enumerate(rows):
            for dx, c in enumerate(row):
                color = {"#": INK, ".": (0, 0, 0, 0), "R": RED}[c]
                sheet.putpixel((left + dx, top + dy), color)
    sheet.save(path)


def write_xml(folder: Path, body: str) -> None:
    (folder / "fonts.xml").write_text(f'<?xml version="1.0"?>\n<fonts>\n{body}\n</fonts>\n')


def font_folder(tmp_path: Path, name: str = "Tiny") -> Path:
    folder = tmp_path / "fonts"
    folder.mkdir()
    make_sheet(folder / "tiny.png")
    write_xml(folder, f'<font name="{name}" type="spritesheet" descent="1" file="tiny.png" />')
    return folder


def ink(image: Image.Image) -> list[str]:
    alpha = (image.getchannel("A") if image.mode == "RGBA" else image).tobytes()
    w = image.width
    return [
        "".join("#" if a else "." for a in alpha[y * w : (y + 1) * w]) for y in range(image.height)
    ]


def test_fonts_xml_lists_spritesheet_fonts(tmp_path):
    folder = font_folder(tmp_path)

    assert read_fonts_xml(folder) == [("Tiny", (folder / "tiny.png").resolve())]


def test_fonts_xml_ignores_truetype_entries(tmp_path):
    folder = font_folder(tmp_path)
    (folder / "Arial.ttf").write_bytes(b"x")
    write_xml(
        folder,
        '<font name="Arial" type="truetype" file="Arial.ttf" />\n'
        '<font name="Tiny" type="spritesheet" file="tiny.png" />',
    )

    assert [name for name, _ in read_fonts_xml(folder)] == ["Tiny"]


def test_fonts_xml_refuses_files_outside_its_folder(tmp_path):
    folder = font_folder(tmp_path)
    make_sheet(tmp_path / "outside.png")
    write_xml(
        folder,
        '<font name="Up" type="spritesheet" file="../outside.png" />\n'
        f'<font name="Absolute" type="spritesheet" file="{tmp_path / "outside.png"}" />',
    )

    assert read_fonts_xml(folder) == []


def test_fonts_xml_refuses_a_symlink_leaving_its_folder(tmp_path):
    folder = font_folder(tmp_path)
    make_sheet(tmp_path / "outside.png")
    try:
        (folder / "link.png").symlink_to(tmp_path / "outside.png")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    write_xml(folder, '<font name="Link" type="spritesheet" file="link.png" />')

    assert read_fonts_xml(folder) == []


def test_fonts_xml_skips_a_missing_png(tmp_path):
    folder = font_folder(tmp_path)
    write_xml(
        folder,
        '<font name="Gone" type="spritesheet" file="gone.png" />\n'
        '<font name="Tiny" type="spritesheet" file="tiny.png" />',
    )

    assert [name for name, _ in read_fonts_xml(folder)] == ["Tiny"]


def test_fonts_xml_with_a_doctype_is_ignored(tmp_path):
    folder = font_folder(tmp_path)
    (folder / "fonts.xml").write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fonts [<!ENTITY n "Tiny">]>\n'
        '<fonts><font name="&n;" type="spritesheet" file="tiny.png" /></fonts>\n'
    )

    assert read_fonts_xml(folder) == []


def test_fonts_xml_is_read_again_after_it_changes(tmp_path):
    folder = font_folder(tmp_path)
    assert [name for name, _ in read_fonts_xml(folder)] == ["Tiny"]

    write_xml(folder, '<font name="Renamed Font" type="spritesheet" file="tiny.png" />')

    assert [name for name, _ in read_fonts_xml(folder)] == ["Renamed Font"]


def test_sheet_height_comes_from_the_first_glyph(tmp_path):
    make_sheet(tmp_path / "s.png")

    assert load_sheet(tmp_path / "s.png").height == 4


def test_sheet_glyphs_are_sliced_at_the_key_colour(tmp_path):
    make_sheet(tmp_path / "s.png")

    sheet = load_sheet(tmp_path / "s.png")

    assert ink(sheet.glyphs[ord("A")]) == [".#..", "#.#.", "###.", "#.#."]
    assert sheet.glyphs[ord(" ")].size == (3, 4)


def test_red_marked_box_is_not_a_glyph(tmp_path):
    make_sheet(tmp_path / "s.png")

    assert ord("C") not in load_sheet(tmp_path / "s.png").glyphs


def test_sheet_text_length_adds_glyph_widths(tmp_path):
    make_sheet(tmp_path / "s.png")

    assert load_sheet(tmp_path / "s.png").getlength("A B") == 11


def test_render_text_with_a_sheet_draws_its_glyph_pixels(tmp_path):
    make_sheet(tmp_path / "s.png")

    image = render_text("AB", load_sheet(tmp_path / "s.png"), RED)

    assert ink(image) == [
        ".#..##.",
        "#.#.###",
        "###.#.#",
        "#.#.###",
    ]
    assert sorted(image.getcolors()) == [(10, (0, 0, 0, 0)), (18, RED)]


def test_render_text_with_a_sheet_stacks_lines_by_its_height(tmp_path):
    make_sheet(tmp_path / "s.png")

    image = render_text("A\nA", load_sheet(tmp_path / "s.png"), RED, line_spacing=1)

    assert image.height == 9


def test_missing_character_uses_the_sheet_fallback_box(tmp_path):
    make_sheet(tmp_path / "s.png")

    image = render_text("C", load_sheet(tmp_path / "s.png"), RED)

    assert ink(image) == ["###", "#.#", "#.#", "###"]


def test_missing_character_is_skipped_when_the_sheet_has_no_fallback(tmp_path):
    make_sheet(tmp_path / "s.png", last=100)

    sheet = load_sheet(tmp_path / "s.png")

    assert sheet.getlength("ACB") == sheet.getlength("AB")


def test_sheet_that_is_not_an_image_is_refused(tmp_path):
    (tmp_path / "s.png").write_bytes(b"not a png")

    with pytest.raises(OSError):
        load_sheet(tmp_path / "s.png")


def test_install_dirs_on_linux(tmp_path):
    exe = tmp_path / "bin" / "aseprite"

    assert install_dirs(str(exe), "linux") == [
        tmp_path / "bin" / "data" / "fonts",
        tmp_path / "share" / "aseprite" / "data" / "fonts",
    ]


def test_install_dirs_on_macos(tmp_path):
    exe = tmp_path / "Aseprite.app" / "Contents" / "MacOS" / "aseprite"

    assert install_dirs(str(exe), "darwin")[-1] == (
        tmp_path / "Aseprite.app" / "Contents" / "Resources" / "data" / "fonts"
    )


def test_install_dirs_on_windows(tmp_path):
    exe = tmp_path / "Aseprite" / "Aseprite.exe"

    assert install_dirs(str(exe), "win32") == [tmp_path / "Aseprite" / "data" / "fonts"]


def test_install_dirs_without_aseprite_is_empty():
    assert install_dirs(None, "linux") == []


def test_bitmap_fonts_found_next_to_the_aseprite_binary(tmp_path):
    (tmp_path / "data").mkdir()
    folder = font_folder(tmp_path / "data")
    exe = tmp_path / "aseprite"

    dirs = sheet_fonts.sheet_dirs([], str(exe), "linux")

    assert dirs == [folder.resolve()]
    assert [(e.name, e.kind) for e in fonts.bitmap_fonts(dirs)] == [("Tiny", "bitmap")]


def test_bitmap_fonts_skip_a_png_that_is_not_a_sheet(tmp_path):
    folder = font_folder(tmp_path)
    (folder / "bad.png").write_bytes(b"junk")
    write_xml(
        folder,
        '<font name="Bad" type="spritesheet" file="bad.png" />\n'
        '<font name="Tiny" type="spritesheet" file="tiny.png" />',
    )

    assert [e.name for e in fonts.bitmap_fonts([folder])] == ["Tiny"]


def test_load_font_ignores_size_for_bitmap_fonts(tmp_path):
    folder = font_folder(tmp_path)
    entry = fonts.bitmap_fonts([folder])[0]

    assert fonts.load_font(entry, 64).height == 4


def test_unknown_font_error_names_the_bitmap_fonts(tmp_path):
    bitmap = FontEntry("Aseprite Mini", "", tmp_path / "mini.png", kind="bitmap")
    other = FontEntry("Pixel Sans", "Regular", tmp_path / "p.ttf")

    with pytest.raises(ToolError, match="Aseprite Mini"):
        find_font("Comic", [other, bitmap])


async def test_font_dirs_setting_with_fonts_xml_adds_bitmap_fonts(tmp_path, monkeypatch):
    folder = font_folder(tmp_path, name="Tiny Pixel")
    monkeypatch.setenv("ASEPRITE_MCP_FONT_DIRS", str(folder))
    monkeypatch.delenv("ASEPRITE_PATH", raising=False)

    _, listed = await server.mcp.call_tool("list_fonts", {"query": "tiny pixel"})
    _, size = await server.mcp.call_tool("measure_text", {"text": "AB", "font": "tiny pixel"})

    assert [(f["name"], f["kind"], f["height"]) for f in listed["fonts"]] == [
        ("Tiny Pixel", "bitmap", 4)
    ]
    assert (size["width"], size["height"], size["line_height"]) == (7, 4, 4)


def test_text_with_a_character_the_sheet_lacks_is_refused_when_the_fallback_is_blank(tmp_path):
    blank = {**GLYPHS, "\x80": ["....", "....", "....", "...."]}
    make_sheet(tmp_path / "s.png", blank)

    with pytest.raises(ToolError, match="no glyph for: C"):
        render_text("ACB", load_sheet(tmp_path / "s.png"), RED)


def test_a_sheet_with_too_many_glyphs_is_refused(tmp_path, monkeypatch):
    make_sheet(tmp_path / "s.png")
    monkeypatch.setattr(sheet_fonts, "MAX_GLYPHS", 10)

    with pytest.raises(ValueError, match="more than"):
        load_sheet(tmp_path / "s.png")


def test_a_gif_named_png_is_not_read_as_a_sheet(tmp_path):
    Image.new("RGBA", (4, 4), KEY).save(tmp_path / "s.png", format="GIF")

    with pytest.raises(OSError):
        load_sheet(tmp_path / "s.png")


def test_fonts_xml_names_with_a_backslash_or_drive_are_refused(tmp_path):
    folder = font_folder(tmp_path)
    write_xml(
        folder,
        '<font name="A" type="spritesheet" file="..\\tiny.png" />'
        '<font name="B" type="spritesheet" file="C:tiny.png" />',
    )

    assert read_fonts_xml(folder) == []
