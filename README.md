# aseprite-mcp

A Model Context Protocol (MCP) server for pixel art. It drives a local
[Aseprite](https://www.aseprite.org/) in batch mode, so an MCP client can create
sprites, draw, animate, fix palettes, inspect the result and export it, all on
ordinary `.aseprite` files you can open in the editor afterwards.

It exposes over 70 tools. Each call starts Aseprite headless with a small Lua
script, applies the change and saves; there is no GUI and no plugin to install.

## Requirements

- Python 3.12 or newer
- Aseprite 1.3 or newer with Lua scripting (tested with 1.3.18, API 41)

You need your own copy of Aseprite: a purchased build (Steam, itch.io, the official
site) or one you compiled from source. This project is not affiliated with Aseprite
or its authors.

## Install

Run it straight from GitHub with uv:

```sh
uvx --from git+https://github.com/hoanganhnvnb/aseprite-mcp aseprite-mcp --check
```

or install it with pipx:

```sh
pipx install git+https://github.com/hoanganhnvnb/aseprite-mcp
```

or from a checkout:

```sh
git clone https://github.com/hoanganhnvnb/aseprite-mcp
cd aseprite-mcp
python -m venv .venv
.venv/bin/pip install -e .
```

Docker is not supported yet.

### Check the setup

```sh
aseprite-mcp --check
```

prints the root folder, sandbox state and timeout, finds Aseprite, runs a tiny
script in it and prints its version and API level. It exits with status 1 and a
hint when Aseprite is missing or cannot run scripts. `aseprite-mcp --version`
prints the server version. Without options the server talks MCP over stdio.

Aseprite is looked up in this order: `ASEPRITE_PATH`, `aseprite` on `PATH`, then
the usual install folders (`/Applications/Aseprite.app` on macOS,
`%ProgramFiles%\Aseprite` and Steam on Windows, Steam and `/usr/bin` on Linux).
When `ASEPRITE_PATH` is set it is the only place looked at, so a typo is reported
instead of silently picking up another binary.

## Client configuration

Most MCP clients take a JSON block like this (Linux / macOS):

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hoanganhnvnb/aseprite-mcp", "aseprite-mcp"],
      "env": {
        "ASEPRITE_PATH": "/Applications/Aseprite.app/Contents/MacOS/aseprite",
        "ASEPRITE_MCP_ROOT": "/home/me/pixel-art"
      }
    }
  }
}
```

If you installed with pipx or pip, use `"command": "aseprite-mcp"` and no `args`.

Windows:

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "aseprite-mcp",
      "env": {
        "ASEPRITE_PATH": "C:\\Program Files\\Aseprite\\Aseprite.exe",
        "ASEPRITE_MCP_ROOT": "C:\\Users\\me\\pixel-art"
      }
    }
  }
}
```

## Configuration

Everything is set through environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `ASEPRITE_PATH` | autodetect | Aseprite executable |
| `ASEPRITE_MCP_ROOT` | server's working directory | Folder that relative paths resolve against |
| `ASEPRITE_MCP_SANDBOX` | off | On refuses any path outside the root |
| `ASEPRITE_TIMEOUT_SECONDS` | `60` | Time limit for one Aseprite run, 1 to 3600 |
| `ASEPRITE_MCP_MAX_PROCS` | CPU count, at most 4 | Aseprite processes allowed at once, 1 to 32 |
| `ASEPRITE_MCP_ALLOW_LUA` | off | On adds the `run_lua` tool (ignored in sandbox mode) |
| `ASEPRITE_MCP_MAX_READ_PIXELS` | `65536` | Most pixels `read_pixels` returns per call, up to 16777216 |
| `ASEPRITE_MCP_MAX_SCAN_PIXELS` | `16777216` | Most pixels `check_animation` scans for overlaps, up to 2^30 |
| `ASEPRITE_MCP_MAX_BATCH_OPS` | `1000` | Most ops one `batch` call accepts, up to 100000 |
| `ASEPRITE_MCP_FONT_DIRS` | none | Extra font folders for `draw_text`, separated like `PATH` |

Flags accept `1`, `true`, `yes` or `on` and `0`, `false`, `no` or `off` (any case);
an empty value means the default. Any other value, or a number outside its range,
stops the server at startup with a message naming the variable.

## Paths

Every tool takes file paths. Relative paths resolve against `ASEPRITE_MCP_ROOT`,
never against wherever Aseprite happens to run, and `~` is expanded. Absolute paths
are used as given unless the sandbox is on, in which case anything that resolves
outside the root (including through `..` or symlinks) is refused.

Tools that write a new file (`export`, `save_copy`, ...) refuse to replace an
existing one unless you pass `overwrite: true`. Edits are written to a temporary
file first and only replace the sprite when the whole run succeeded, so a failed or
timed-out call leaves the original untouched. The new file keeps the old one's
permissions, but it is a new file: hard links to the old one are not updated. A
read-only file is refused before anything runs. Calls on the same file run one after
another.

## File formats

Work in `.aseprite` files: only they keep layers, groups, tilemaps, tags and slices.
Other formats store one flattened image (`.gif` also keeps frames, without tags), so an
edit that would leave a `.png` or `.gif` with more than one layer, a tilemap, a tag or
a slice is refused and the file stays as it was. `flatten_sprite` in the same batch
makes such an edit fit, and `save_copy` turns any file into an `.aseprite` to work on.
Opening `walk_1.png` reads that one file, never `walk_2.png` and the rest of a
numbered sequence. `save_copy` and `export` write flattened copies on purpose.

## Conventions

- Frames, layer stack positions and palette indices count from 1, as in the editor.
- Colours are `"#RRGGBB"`, `"#RRGGBBAA"` or `"transparent"`.
- Frame lists are `3`, `"1-4"`, `"1-4,7"` or `"all"`.
- Rectangles are `{"x": 0, "y": 0, "w": 16, "h": 16}`.
- Layers inside groups are named by path: `"body/arm"`.
- A locked layer (or one inside a locked group) refuses pixel and cel edits, deleting
  and merging; `update_layer` can still rename, hide or unlock it. Whole-sprite
  changes (resize, crop, colour mode, flatten, flip and rotate without a layer)
  ignore locks, as in the editor.

## Tools

| Group | Tools |
|---|---|
| Sprite | `create_sprite`, `get_sprite_info`, `set_color_mode`, `resize_sprite`, `crop_sprite`, `save_copy` |
| Layers | `add_layer` (normal, group or tilemap), `update_layer`, `delete_layer`, `duplicate_layer`, `merge_layer_down`, `flatten_sprite` |
| Frames and tags | `add_frames`, `delete_frames`, `set_frame_duration`, `copy_frames`, `set_tag`, `delete_tag` |
| Cels | `set_cel`, `clear_cels`, `tween_cels`, `oscillate_cels` |
| Drawing | `draw_pixels`, `draw_line`, `draw_rect`, `draw_ellipse`, `draw_polygon`, `fill_area`, `draw_gradient`, `fill_pattern`, `draw_ascii`, `draw_isometric_box` |
| Text | `list_fonts`, `measure_text`, `draw_text` |
| Regions and transforms | `move_region`, `erase_region`, `flip`, `rotate` |
| Colour | `get_palette`, `set_palette`, `generate_color_ramp`, `extract_palette`, `quantize_to_palette`, `replace_colors`, `adjust_colors`, `outline`, `apply_convolution` |
| Reading | `read_pixels`, `view_sprite`, `get_bounds`, `compare_frames`, `get_color_stats`, `find_stray_pixels` |
| Animation checks | `check_animation`, `repair_animation`, `copy_layers` |
| Slices | `create_slice`, `update_slice`, `list_slices`, `delete_slice` |
| Tilemaps | `get_tilemap_info`, `draw_tile`, `set_tiles` |
| Export and import | `export`, `export_spritesheet`, `export_layers`, `import_image`, `start_preview`, `stop_preview` |
| Other | `batch`, `pixel_art_guide`, `run_lua` (opt-in) |

Every tool has a short description and a typed schema, which is what the client
sees. Read-only tools never touch the file.

There is also a `pixel_art_guide` prompt (topics: basics, animation, idle, walk,
attack, effects) and an `aseprite://palettes` resource listing the palette presets
that `set_palette` accepts.

### Batch

Each tool call is one Aseprite run. `batch` runs several single-step tools on one
sprite in a single run and saves once at the end; if any step fails nothing is
saved and the error names the step. One call takes up to 1000 ops
(`ASEPRITE_MCP_MAX_BATCH_OPS`). Pass the arguments of each tool without `path`:

```json
{
  "path": "hero.aseprite",
  "ops": [
    {"tool": "add_layer", "args": {"name": "body"}},
    {"tool": "draw_rect", "args": {"layer": "body", "rect": {"x": 4, "y": 4, "w": 8, "h": 12}, "color": "#2b2b44", "fill": true}},
    {"tool": "outline", "args": {"layer": "body", "color": "#000000"}},
    {"tool": "set_frame_duration", "args": {"duration_ms": 120, "frames": "all"}}
  ]
}
```

`create_sprite`, `view_sprite` and the other tools that need more than one step
are not accepted; the error lists the ones that are.

### Looking at the result

`view_sprite` returns a PNG of one or more frames (up to 64) on a checkerboard,
plus a short text description. It picks a scale that keeps the image within
512 px unless you pass `scale`, and never goes beyond 2048 px per side. It can
draw a pixel grid and rulers, zoom into a region and show onion skin of the
previous frames.

To watch an exported GIF in a browser, `start_preview` serves a folder over HTTP
and returns a URL; `stop_preview` stops it.

## Security

- The sandbox is off by default because most setups run the server for one
  person on their own files. Set `ASEPRITE_MCP_SANDBOX=1` to keep every read and
  write inside `ASEPRITE_MCP_ROOT`.
- `run_lua` runs arbitrary Lua inside Aseprite, which can read and write any file
  and start programs. It is only registered when `ASEPRITE_MCP_ALLOW_LUA=1`, and
  never in sandbox mode.
- The preview server binds to 127.0.0.1 only, requires a random token in the URL,
  checks the `Host` header, serves image and JSON files from the chosen folder and
  nothing else, and stops with the server.
- Input sizes are capped (canvas 4096x4096, pixel lists, reads, view size) so a
  bad request ends with a clear error instead of a hung process.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -m "not aseprite"
```

Tests marked `aseprite` run the real editor and are skipped when it cannot be
found. To run them, point `ASEPRITE_PATH` at your Aseprite:

```sh
ASEPRITE_PATH=/path/to/aseprite .venv/bin/pytest
```

CI runs lint and the unit tests on Linux, macOS and Windows.

`bench/bench.py` times a few common calls against a real Aseprite:

```sh
ASEPRITE_PATH=/path/to/aseprite .venv/bin/python bench/bench.py
```

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 HoangAnh.
