<div align="center">

<!-- banner: animated banner image goes here, e.g. <img src="assets/banner.gif" alt="aseprite-mcp" width="720"> -->

# aseprite-mcp

**Pixel art for your AI assistant, made in a real Aseprite.**

An [MCP](https://modelcontextprotocol.io/) server that drives a local
[Aseprite](https://www.aseprite.org/) in batch mode: create sprites, draw, animate, fix
palettes, look at the result and export it. Everything lands in ordinary `.aseprite`
files you can open in the editor.

[![CI](https://github.com/hoanganhnvnb/aseprite-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/hoanganhnvnb/aseprite-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-server-informational.svg)](https://modelcontextprotocol.io/)

</div>

<!-- showcase -->

## Quick start

You need Python 3.12+ and your own copy of Aseprite 1.3 or newer.

**1. Install.**

```sh
uvx --from git+https://github.com/hoanganhnvnb/aseprite-mcp aseprite-mcp --check
```

or `pipx install git+https://github.com/hoanganhnvnb/aseprite-mcp` (Python 3.12 or newer; `uvx`
fetches one for you). `--check` finds Aseprite and runs a tiny script in it; set
`ASEPRITE_PATH` if it cannot.

**2. Add it to your MCP client.**

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hoanganhnvnb/aseprite-mcp", "aseprite-mcp"],
      "env": {
        "ASEPRITE_PATH": "/path/to/aseprite",
        "ASEPRITE_MCP_ROOT": "/home/me/pixel-art"
      }
    }
  }
}
```

**3. Ask.**

> Create a 32x32 sprite called `slime.aseprite`, draw a small green slime with a dark
> outline, then show it to me.

More in [Getting started](docs/getting-started.md).

## Highlights

| Feature | What it gives you |
|---|---|
| **Batch** | `batch` runs many edits in one Aseprite process and saves once; if a step fails, nothing is saved. |
| **Safe saves** | Edits go to a temporary file and replace the sprite only on success. An optional sandbox keeps every path inside one folder. |
| **Native image ops** | Colour adjustment, convolution, outlines and sprite sheets run on Aseprite's own filters and exporter. |
| **Cross-platform** | Linux, macOS and Windows; CI runs the unit tests on all three. |
| **Preview** | `view_sprite` returns a PNG of any frames; `start_preview` serves exported GIFs on localhost. |
| **Opt-in Lua** | `run_lua` exists only when you set `ASEPRITE_MCP_ALLOW_LUA=1`, and never in sandbox mode. |

## Tools

72 tools, plus `run_lua` when enabled. Full parameters in [docs/tools.md](docs/tools.md).

| Group | Examples |
|---|---|
| [Sprite](docs/tools.md#sprite) | `create_sprite`, `resize_sprite`, `save_copy` |
| [Layers](docs/tools.md#layers) | `add_layer`, `update_layer`, `flatten_sprite` |
| [Frames and tags](docs/tools.md#frames-and-tags) | `add_frames`, `set_frame_duration`, `set_tag` |
| [Cels](docs/tools.md#cels) | `set_cel`, `tween_cels`, `oscillate_cels` |
| [Drawing](docs/tools.md#drawing) | `draw_rect`, `draw_polygon`, `draw_gradient`, `draw_ascii` |
| [Text](docs/tools.md#text) | `list_fonts`, `measure_text`, `draw_text` |
| [Regions and transforms](docs/tools.md#regions-and-transforms) | `move_region`, `flip`, `rotate` |
| [Colour](docs/tools.md#colour) | `set_palette`, `generate_color_ramp`, `outline`, `quantize_to_palette` |
| [Reading](docs/tools.md#reading) | `view_sprite`, `read_pixels`, `find_stray_pixels` |
| [Animation checks](docs/tools.md#animation-checks) | `check_animation`, `repair_animation`, `copy_layers` |
| [Slices](docs/tools.md#slices) | `create_slice`, `update_slice`, `list_slices` |
| [Tilemaps](docs/tools.md#tilemaps) | `get_tilemap_info`, `draw_tile`, `set_tiles` |
| [Export and import](docs/tools.md#export-and-import) | `export`, `export_spritesheet`, `import_image`, `start_preview` |
| [Other](docs/tools.md#other) | `batch`, `pixel_art_guide`, `run_lua` (opt-in) |

There is also a `pixel_art_guide` prompt and an `aseprite://palettes` resource with the
palette presets `set_palette` accepts.

## Documentation

- [Getting started](docs/getting-started.md): install, find Aseprite, client setup, first prompt
- [Concepts](docs/concepts.md): 1-based frames, colours, layer paths, locks, file formats, limits
- [Batch](docs/batch.md): many edits in one Aseprite run
- [Fonts](docs/fonts.md): system fonts and Aseprite's pixel fonts
- [Configuration](docs/configuration.md): every environment variable
- [Security](docs/security.md): sandbox, `run_lua`, preview server, atomic saves
- [Troubleshooting](docs/troubleshooting.md): error messages and fixes
- [Tool reference](docs/tools.md): every tool with its parameters

## Fan art

Showcase sprites are unofficial fan art, see [assets/NOTICE.md](assets/NOTICE.md). They are not covered by
the MIT license. This project is not affiliated with Aseprite or its authors.

## Contributing

Issues and pull requests are welcome; start with [CONTRIBUTING.md](CONTRIBUTING.md). To
report a vulnerability, see [SECURITY.md](SECURITY.md). Changes are listed in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 HoangAnh.
