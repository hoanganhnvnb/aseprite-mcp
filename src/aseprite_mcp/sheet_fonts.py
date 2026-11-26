"""Aseprite's own pixel fonts ("spritesheet" fonts), read from its installation.

They are not shipped here: they are found in Aseprite's data/fonts folder, which
lists them in fonts.xml next to their PNG sheets.

Sheet layout, as Aseprite reads it: the top-left pixel is the key colour. Glyph boxes
are found by scanning a row left to right; a box is the run of non-key pixels from
its top-left pixel to the right (width) and downwards (height). After the last box of
a row the scan moves down by that box's height, then on one row at a time. Boxes stand
for code points 32, 33, 34... in the order found. A box whose top-left pixel is pure
red is a placeholder for a code point the font lacks. Only the alpha of a box is
used, so glyphs take the text colour. The first box (the space) sets the line height.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

FIRST_CODE = 32
# Aseprite measures a character the sheet lacks with the glyph of code point 128.
FALLBACK_CODE = 128
MISSING_MARK = (255, 0, 0, 255)
MAX_XML_BYTES = 256 * 1024
MAX_SHEET_PIXELS = 2048 * 2048
MAX_GLYPHS = 65536
Stamp = tuple[int, int]


@dataclass(frozen=True)
class SheetFont:
    height: int
    glyphs: dict[int, Image.Image]

    def glyph(self, char: str) -> Image.Image | None:
        code = ord(char)
        # Aseprite skips these control characters instead of drawing a box.
        if 10 <= code <= 20:
            return None
        found = self.glyphs.get(code)
        return found if found is not None else self.glyphs.get(FALLBACK_CODE)

    def lacks(self, char: str) -> bool:
        """True if the font cannot show char: no glyph, and a blank fallback glyph."""
        code = ord(char)
        if 10 <= code <= 20 or code in self.glyphs:
            return False
        fallback = self.glyphs.get(FALLBACK_CODE)
        return fallback is None or fallback.getbbox() is None

    def getlength(self, text: str) -> int:
        return sum(g.width for g in map(self.glyph, text) if g is not None)

    def draw(self, mask: Image.Image, xy: tuple[int, int], text: str) -> None:
        x, y = xy
        for glyph in map(self.glyph, text):
            if glyph is not None:
                mask.paste(255, (x, y), glyph)
                x += glyph.width


def _boxes(image: Image.Image) -> list[tuple[int, int, int, int] | None]:
    px = image.load()
    width, height = image.size
    key = px[0, 0]
    boxes: list[tuple[int, int, int, int] | None] = []
    x, y, step = 0, 0, 1
    while True:
        if x >= width:
            x, y, step = 0, y + step, 1
            if y >= height:
                return boxes
            continue
        if px[x, y] == key:
            x += 1
            continue
        w = 1
        while x + w < width and px[x + w, y] != key:
            w += 1
        h = 1
        while y + h < height and px[x, y + h] != key:
            h += 1
        if len(boxes) >= MAX_GLYPHS:
            raise ValueError(f"the sheet has more than {MAX_GLYPHS} glyphs")
        boxes.append(None if px[x, y] == MISSING_MARK else (x, y, x + w, y + h))
        x += w
        step = h


def _read_sheet(path: Path) -> SheetFont:
    try:
        with Image.open(path, formats=["PNG"]) as image:
            if image.width * image.height > MAX_SHEET_PIXELS:
                raise ValueError(f"{path.name} is larger than {MAX_SHEET_PIXELS} pixels")
            rgba = image.convert("RGBA")
    except Image.DecompressionBombError as e:
        raise ValueError(str(e)) from None
    boxes = _boxes(rgba)
    if not boxes:
        raise ValueError(f"{path.name} has no glyphs")
    alpha = rgba.getchannel("A")
    glyphs = {FIRST_CODE + i: alpha.crop(box) for i, box in enumerate(boxes) if box is not None}
    first = boxes[0]
    return SheetFont(height=first[3] - first[1] if first else 1, glyphs=glyphs)


def _stamp(path: Path) -> Stamp | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


_sheets: dict[Path, tuple[Stamp, SheetFont]] = {}


def load_sheet(path: Path) -> SheetFont:
    """The sheet at path, cached until the file changes. Raises OSError or ValueError."""
    stamp = _stamp(path)
    if stamp is None:
        raise FileNotFoundError(path)
    cached = _sheets.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    sheet = _read_sheet(path)
    _sheets[path] = (stamp, sheet)
    return sheet


def _inside(folder: Path, name: str) -> Path | None:
    """The PNG file `name` refers to, or None if it is missing or outside folder."""
    parts = re.split(r"[\\/]", name)
    if ":" in name or any(p in ("", ".", "..") for p in parts):
        return None
    try:
        root = folder.resolve()
        path = root.joinpath(*parts).resolve()
    except (OSError, RuntimeError):
        return None
    if not path.is_relative_to(root) or path.suffix.lower() != ".png" or not path.is_file():
        return None
    return path


def _parse(folder: Path, data: bytes) -> list[tuple[str, Path]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    # The file is not ours: no DTD means no entity expansion of any kind.
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return []
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return []
    found = []
    for font in root.findall("font"):
        file = font.get("file")
        if font.get("type") != "spritesheet" or not file:
            continue
        path = _inside(folder, file)
        if path is not None:
            found.append((font.get("name") or file, path))
    return found


_xml: dict[Path, tuple[Stamp, list[tuple[str, Path]]]] = {}


def read_fonts_xml(folder: Path) -> list[tuple[str, Path]]:
    """(name, sheet path) of the spritesheet fonts listed in folder/fonts.xml.

    Entries whose file is missing or lies outside the folder (also through a
    symlink) are left out; an unreadable or oversized fonts.xml lists nothing.
    """
    xml = folder / "fonts.xml"
    stamp = _stamp(xml)
    if stamp is None or stamp[1] > MAX_XML_BYTES:
        return []
    cached = _xml.get(xml)
    if cached is None or cached[0] != stamp:
        try:
            data = xml.read_bytes()[:MAX_XML_BYTES]
        except OSError:
            return []
        cached = (stamp, _parse(folder, data))
        _xml[xml] = cached
    root = folder.resolve()
    return [
        (name, path)
        for name, path in cached[1]
        if path.is_file() and _inside(root, path.relative_to(root).as_posix())
    ]


def install_dirs(exe: str | None, platform: str) -> list[Path]:
    """Where an Aseprite installation keeps data/fonts, relative to its executable."""
    if not exe:
        return []
    try:
        bin_dir = Path(exe).resolve().parent
    except (OSError, RuntimeError):
        return []
    dirs = [bin_dir / "data" / "fonts"]
    if platform == "darwin":
        dirs.append(bin_dir.parent / "Resources" / "data" / "fonts")
    elif platform != "win32":
        dirs.append(bin_dir.parent / "share" / "aseprite" / "data" / "fonts")
    return dirs


def sheet_dirs(font_dirs: Iterable[Path], exe: str | None, platform: str) -> list[Path]:
    """Folders with a fonts.xml: any of font_dirs, then the first one of the installation."""
    found: list[Path] = []
    for folder in font_dirs:
        if (folder / "fonts.xml").is_file():
            found.append(folder.resolve())
    for folder in install_dirs(exe, platform):
        if (folder / "fonts.xml").is_file():
            found.append(folder.resolve())
            break
    return list(dict.fromkeys(found))
