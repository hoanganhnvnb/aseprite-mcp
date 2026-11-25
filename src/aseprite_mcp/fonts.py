"""Font discovery and text rasterising with Pillow.

Text is laid out by Pillow (FreeType). Limitations: colour glyphs (emoji fonts) are
not supported; characters missing from the font show the font's own fallback glyph,
usually an empty box; right-to-left and other complex scripts are shaped only when
Pillow has libraqm and letter_spacing is 0, since spaced text is placed one character
at a time.
"""

import difflib
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .colors import RGBA
from .config import Settings
from .errors import ToolError
from .paths import resolve_path

FONT_EXTENSIONS = frozenset({".ttf", ".otf", ".ttc", ".otc"})
COLLECTIONS = frozenset({".ttc", ".otc"})
MAX_FACES = 64
MAX_SIZE = 256
MAX_SIDE = 2048
MAX_CHARS = 2000
# Room around the laid-out text for overhanging glyphs, outline and shadow.
MAX_OUTLINE = 8
MAX_SHADOW = 16

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@dataclass(frozen=True)
class FontEntry:
    family: str
    style: str
    path: Path
    index: int = 0

    @property
    def name(self) -> str:
        return f"{self.family} {self.style}".strip()


def font_dirs(platform: str, env: Mapping[str, str], home: Path | None = None) -> list[Path]:
    """Folders to search for fonts: ASEPRITE_MCP_FONT_DIRS first, then the system ones."""
    home = home if home is not None else Path.home()
    dirs = [Path(p).expanduser() for p in env.get("ASEPRITE_MCP_FONT_DIRS", "").split(os.pathsep)]
    dirs = [d for d in dirs if str(d) not in ("", ".")]
    if platform == "win32":
        windir = env.get("WINDIR") or env.get("SYSTEMROOT")
        if windir:
            dirs.append(Path(windir) / "Fonts")
        if env.get("LOCALAPPDATA"):
            dirs.append(Path(env["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    elif platform == "darwin":
        dirs += [
            Path("/System/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"),
            Path("/Library/Fonts"),
            home / "Library" / "Fonts",
        ]
    else:
        dirs += [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            home / ".local" / "share" / "fonts",
            home / ".fonts",
        ]
    unique: list[Path] = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


def _faces(path: Path) -> list[FontEntry]:
    found: list[FontEntry] = []
    # Skips broken links, and pipes or devices that would block on open.
    if not path.is_file():
        return found
    count = MAX_FACES if path.suffix.lower() in COLLECTIONS else 1
    for index in range(count):
        try:
            family, style = ImageFont.truetype(str(path), 12, index=index).getname()
        except (OSError, ValueError):
            break
        found.append(FontEntry(family or path.stem, style or "", path, index))
    return found


def _font_files(dirs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in dirs:
        # Symlinked folders are not followed, so a link loop cannot hang the scan.
        for folder, _, names in os.walk(root, onerror=lambda e: None):
            files += [
                Path(folder) / n for n in sorted(names) if Path(n).suffix.lower() in FONT_EXTENSIONS
            ]
    return files


def _sorted(entries: Iterable[FontEntry]) -> list[FontEntry]:
    return sorted(entries, key=lambda e: (e.name.casefold(), str(e.path), e.index))


def scan_fonts(dirs: Iterable[Path]) -> list[FontEntry]:
    """Every face in the font files below dirs; unreadable folders and files are skipped."""
    return _sorted(face for f in _font_files(dirs) for face in _faces(f))


Stamp = tuple[tuple[Path, int, int], ...]


def _stamp(files: Iterable[Path]) -> Stamp:
    stamps = []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        stamps.append((f, st.st_mtime_ns, st.st_size))
    return tuple(stamps)


_cache: dict[tuple[Path, ...], tuple[Stamp, list[FontEntry]]] = {}


def installed_fonts(dirs: Sequence[Path]) -> list[FontEntry]:
    """scan_fonts, cached until a font file under dirs is added, removed or changed.

    Checking only lists the folders and stats the files, which is far cheaper than
    opening every font. Folder mtimes alone are not enough: they can stay the same
    when a file is added within the filesystem's timestamp granularity.
    """
    key = tuple(dirs)
    files = _font_files(dirs)
    stamp = _stamp(files)
    cached = _cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    entries = _sorted(face for f in files for face in _faces(f))
    _cache[key] = (stamp, entries)
    return entries


def _looks_like_path(name: str) -> bool:
    return name.startswith("~") or Path(name).is_absolute()


def _font_file(name: str, settings: Settings | None) -> FontEntry:
    if settings is None:
        raise ToolError("font paths are not accepted here")
    path = resolve_path(name, settings, must_exist=True)
    if path.suffix.lower() not in FONT_EXTENSIONS:
        allowed = ", ".join(sorted(FONT_EXTENSIONS))
        raise ToolError(f"{path.name} is not a font file; use one of: {allowed}")
    faces = _faces(path)
    if not faces:
        raise ToolError(f"Cannot read the font {path}")
    return faces[0]


def _regular_first(entry: FontEntry) -> tuple[int, str]:
    plain = entry.style.casefold() in ("regular", "book", "normal", "roman", "")
    return (0 if plain else 1, entry.name.casefold())


def find_font(
    name: str, entries: Sequence[FontEntry], settings: Settings | None = None
) -> FontEntry:
    """Find a font by name, case-insensitively, or load it from an absolute or ~ path.

    A name matches the full name ("Family Style"), then the file name without its
    extension, then the family (preferring its regular style). Paths go through the
    usual path rules, so the sandbox applies.
    """
    name = name.strip()
    if _looks_like_path(name):
        return _font_file(name, settings)
    key = name.casefold()
    for match in (
        lambda e: e.name.casefold() == key,
        lambda e: e.path.stem.casefold() == key,
        lambda e: e.family.casefold() == key,
    ):
        hits = [e for e in entries if match(e)]
        if hits:
            return min(hits, key=_regular_first)
    if not entries:
        raise ToolError(
            f"Font {name!r} not found: no fonts are installed. Leave font empty for the "
            "built-in font or add a folder to ASEPRITE_MCP_FONT_DIRS"
        )
    names = {e.name.casefold(): e.name for e in entries}
    names.update({e.family.casefold(): e.family for e in entries})
    close = difflib.get_close_matches(key, list(names), n=10, cutoff=0.6)
    hint = f" Close matches: {', '.join(names[c] for c in close)}." if close else ""
    raise ToolError(f"Font {name!r} not found.{hint} Call list_fonts to see the installed fonts.")


def load_font(entry: FontEntry | None, size: int) -> Font:
    """The font at `size` px (the pixel size FreeType renders at); None = Pillow's own font."""
    if not 1 <= size <= MAX_SIZE:
        raise ToolError(f"Font size must be between 1 and {MAX_SIZE}, got {size}")
    try:
        if entry is None:
            return ImageFont.load_default(size)
        return ImageFont.truetype(str(entry.path), size, index=entry.index)
    except (OSError, ValueError) as e:
        shown = entry.name if entry is not None else "the built-in font"
        raise ToolError(f"Cannot load {shown} at size {size}: {e}") from None


def _line_height(font: Font) -> int:
    if isinstance(font, ImageFont.FreeTypeFont):
        ascent, descent = font.getmetrics()
        return ascent + descent
    return int(font.getbbox("Ag")[3])


def _shift(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    out = Image.new(mask.mode, mask.size, 0)
    out.paste(mask, (dx, dy))
    return out


def _dilate(mask: Image.Image, steps: int) -> Image.Image:
    """Grow the mask by `steps` pixels towards left, right, up and down (a diamond)."""
    for _ in range(steps):
        grown = mask
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            grown = ImageChops.lighter(grown, _shift(mask, dx, dy))
        mask = grown
    return mask


def _paint(mask: Image.Image, color: RGBA) -> Image.Image:
    layer = Image.new("RGBA", mask.size, (*color[:3], 0))
    alpha = color[3]
    layer.putalpha(mask if alpha == 255 else mask.point(lambda v: (v * alpha + 127) // 255))
    return layer


def _too_big(w: int, h: int) -> ToolError:
    return ToolError(
        f"The text would be {w}x{h} px; the limit is {MAX_SIDE}x{MAX_SIDE}. "
        "Use a smaller size or less text"
    )


def render_text(
    text: str,
    font: Font,
    color: RGBA,
    *,
    bold: bool = False,
    antialias: bool = False,
    outline: RGBA | None = None,
    outline_width: int = 1,
    shadow: RGBA | None = None,
    shadow_dx: int = 1,
    shadow_dy: int = 1,
    letter_spacing: int = 0,
    line_spacing: int = 0,
) -> Image.Image:
    """Render text into an RGBA image cropped to the painted pixels.

    Lines split on "\\n" and start line-height + line_spacing px apart. bold adds a copy
    of the glyphs 1 px to the right. Without antialias, glyph coverage is cut at 128 to
    fully opaque or fully transparent; with it, partial coverage stays as partial alpha.
    The outline grows the glyphs by outline_width px towards the four sides (diamond
    corners) and sits under them; the shadow is the glyphs plus outline moved by
    (shadow_dx, shadow_dy), under everything. Empty or blank text gives a 0x0 image.
    """
    if len(text) > MAX_CHARS:
        raise ToolError(f"The text has {len(text)} characters; the limit is {MAX_CHARS}")
    if not 1 <= outline_width <= MAX_OUTLINE:
        raise ToolError(f"outline_width must be between 1 and {MAX_OUTLINE}")
    if max(abs(shadow_dx), abs(shadow_dy)) > MAX_SHADOW:
        raise ToolError(f"shadow offsets must be between -{MAX_SHADOW} and {MAX_SHADOW}")
    lines = text.split("\n")
    line_h = _line_height(font)
    pitch = line_h + line_spacing
    tops = [i * pitch for i in range(len(lines))]
    first = min(tops)

    def advance(line: str) -> float:
        if letter_spacing == 0:
            return font.getlength(line)
        return sum(font.getlength(c) for c in line) + letter_spacing * max(len(line) - 1, 0)

    widths = [advance(line) for line in lines]
    grow = outline_width if outline is not None else 0
    sx, sy = (abs(shadow_dx), abs(shadow_dy)) if shadow is not None else (0, 0)
    layout_w = max(0, int(max(widths) + 0.5)) + int(bold)
    layout_h = max(tops) - first + line_h
    if layout_w + 2 * grow + sx > MAX_SIDE or layout_h + 2 * grow + sy > MAX_SIDE:
        raise _too_big(layout_w + 2 * grow + sx, layout_h + 2 * grow + sy)

    pad = line_h + MAX_OUTLINE + MAX_SHADOW + 2
    mask = Image.new("L", (layout_w + 2 * pad, layout_h + 2 * pad), 0)
    draw = ImageDraw.Draw(mask)
    draw.fontmode = "L"
    anchor = "la" if isinstance(font, ImageFont.FreeTypeFont) else None
    for line, top in zip(lines, tops):
        y = pad + top - first
        if letter_spacing == 0:
            draw.text((pad, y), line, font=font, fill=255, anchor=anchor)
            continue
        x = float(pad)
        for char in line:
            draw.text((round(x), y), char, font=font, fill=255, anchor=anchor)
            x += font.getlength(char) + letter_spacing
    if bold:
        mask = ImageChops.lighter(mask, _shift(mask, 1, 0))
    if not antialias:
        mask = mask.point(lambda v: 255 if v >= 128 else 0)

    box = mask.getbbox()
    if box is None:
        return Image.new("RGBA", (0, 0))
    left, top, right, bottom = box
    margin = grow + MAX_SHADOW
    glyphs = mask.crop((left - margin, top - margin, right + margin, bottom + margin))

    out = Image.new("RGBA", glyphs.size, (0, 0, 0, 0))
    ring = _dilate(glyphs, grow) if outline is not None else glyphs
    if shadow is not None:
        out = Image.alpha_composite(out, _paint(_shift(ring, shadow_dx, shadow_dy), shadow))
    if outline is not None:
        out = Image.alpha_composite(out, _paint(ring, outline))
    out = Image.alpha_composite(out, _paint(glyphs, color))

    box = out.getchannel("A").getbbox()
    if box is None:
        return Image.new("RGBA", (0, 0))
    out = out.crop(box)
    if out.width > MAX_SIDE or out.height > MAX_SIDE:
        raise _too_big(out.width, out.height)
    return out
