# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Homepage README and a `docs/` folder: getting started, concepts, batch, configuration,
  security, troubleshooting and fonts.
- `docs/tools.md`, the tool reference, generated from the registry by
  `scripts/gen_tool_docs.py`.
- Contributing and security policies, issue and pull request templates.
- Tests that keep the docs honest: generated reference up to date, tool names, environment
  variables and links valid.

## [0.1.0] - 2026-11-25

The first version (date of the first commit).

### Added

- MCP server over stdio that drives a local Aseprite in batch mode: 72 tools, plus
  `run_lua` when enabled.
- Sprites, layers (groups and tilemap layers), frames, tags, cels, slices and tilemaps.
- Drawing: pixels, lines, rectangles, ellipses, polygons, flood fill, gradients, dither
  patterns, text-art, isometric boxes and text with system and Aseprite pixel fonts.
- Colour: palettes and presets, colour ramps, palette extraction and quantising, colour
  replacement and adjustment, outlines, convolution.
- Reading: pixel reads, `view_sprite` PNG previews, bounds, frame comparison, colour
  statistics, stray pixel detection.
- Animation checks and repair, tweened and oscillating cels.
- Export to images, sprite sheets and per-layer PNGs, image import, and a localhost
  preview server.
- `batch`: many edits in one Aseprite run, saved once.
- Optional sandbox, opt-in `run_lua`, atomic saves and per-file locking.
- `aseprite-mcp --check` and `--version`; settings through environment variables.
- A `pixel_art_guide` prompt and an `aseprite://palettes` resource.
- Continuous integration on Linux, macOS and Windows with Python 3.12 and 3.13.
