# Fonts

`draw_text` renders text onto a layer; `list_fonts` shows what is available and
`measure_text` tells how big some text would be without touching a sprite.

## Two kinds of fonts

| Kind | Where it comes from | Notes |
|---|---|---|
| `truetype` | `.ttf`, `.otf`, `.ttc`, `.otc` files in the system font folders and in `ASEPRITE_MCP_FONT_DIRS` | Any size; antialiasing is optional |
| `bitmap` | Aseprite's own pixel fonts, e.g. "Aseprite" and "Aseprite Mini" | Fixed height; `size` and `antialias` do not change them |

Leave `font` empty to use the small built-in font.

## System fonts

The server searches these folders, after any in `ASEPRITE_MCP_FONT_DIRS`:

- Linux: `/usr/share/fonts`, `/usr/local/share/fonts`, `~/.local/share/fonts`, `~/.fonts`
- macOS: `/System/Library/Fonts`, `/System/Library/Fonts/Supplemental`, `/Library/Fonts`,
  `~/Library/Fonts`
- Windows: `%WINDIR%\Fonts` and `%LOCALAPPDATA%\Microsoft\Windows\Fonts`

Pass a font to `draw_text` by the name `list_fonts` shows (family, `Family Style` or file
name, any case) or by the absolute path of a font file. With the sandbox on, a font file
outside the root is refused.

## Your own folders

```json
"env": { "ASEPRITE_MCP_FONT_DIRS": "/home/me/fonts:/home/me/pixel-fonts" }
```

Separate folders like `PATH` (`;` on Windows). A new font file shows up without a restart.

## Aseprite's pixel fonts

They are read from your Aseprite installation (its `data/fonts` folder, which lists them
in `fonts.xml` next to their PNG sheets). This project **never bundles** them: if
`list_fonts` shows no `bitmap` fonts, the installation could not be found or does not have
that folder. A folder in `ASEPRITE_MCP_FONT_DIRS` that holds an Aseprite `fonts.xml` adds
its pixel fonts too, so you can keep a copy elsewhere.

## Characters a font lacks

- A TrueType font draws its own fallback glyph, usually an empty box.
- A bitmap font that has no glyph for a character and whose fallback glyph is blank (such
  as "Aseprite Mini") **refuses** the text: the error lists the missing characters.
- Colour emoji fonts are not supported.
- Right-to-left and other complex scripts are shaped only when Pillow has libraqm and
  `letter_spacing` is 0.

Text is at most 2000 characters and 2048 x 2048 px.
