# Concepts

The conventions every tool shares. The server's own instructions tell the assistant the
same things.

## Counting

Frames, layer stack positions and palette indices count from **1**, as in the editor.
Frame lists are `3`, `"1-4"`, `"1-4,7"` or `"all"`. Rectangles are
`{"x": 0, "y": 0, "w": 16, "h": 16}`.

## Colours

`"#RRGGBB"`, `"#RRGGBBAA"` or `"transparent"`. Palettes come back as `#rrggbb`
(`#rrggbbaa` when a colour is not opaque).

## Layer paths

Layers inside groups are named by path: `"body/arm"` is the layer `arm` in the group
`body`. Where a layer is optional, an empty name means the bottom-most normal layer.
Keep names unique and free of `/`: a repeated name finds the shallowest layer with it,
and a layer named `x/y` shadows the path `x/y` of a layer inside group `x`.
`get_sprite_info` shows the layer tree and says when a path is ambiguous.

## Locks

A locked layer, or one inside a locked group, refuses pixel and cel edits, deleting and
merging. `update_layer` can still rename, hide or unlock it. Whole-sprite changes
(resize, crop, colour mode, flatten, flip and rotate without a layer) ignore locks, as in
the editor. This is separate from the per-file locks the server uses to keep calls apart,
see [security](security.md#lock-scope).

## Linked cels

A linked cel shares its image with cels in other frames. `set_cel` gives a linked cel its
own copy before it moves or fades, so frames outside the list never change.
`copy_frames` with `link: true` makes the copies linked cels instead. Colour tools such
as `replace_colors` change a linked cel once; if it is also linked to frames outside the
list, it gets its own copy, and only when some of its pixels change.

## The Background layer

Aseprite can flag a layer as Background. It cannot hold transparent pixels, so alpha is
ignored on it: drawing with a transparent colour or erasing gives opaque black, new frames
are filled with the background colour, and rotating by 90 or 270 degrees needs a square
canvas. Ordinary layers are not affected.

## File formats

Work in `.aseprite` files: only they keep layers, groups, tilemaps, tags and slices.
Other formats store one flattened image (`.gif` also keeps frames, without tags). An edit
that would leave a `.png` or `.gif` with more than one layer, a tilemap, a tag or a slice
is refused and the file stays as it was. `flatten_sprite` in the same batch makes such an
edit fit, and `save_copy` turns any file into an `.aseprite` to work on. Opening
`walk_1.png` reads that one file, never `walk_2.png` and the rest of a numbered
sequence. `save_copy` and `export` write flattened copies on purpose.

## Paths

Relative paths resolve against `ASEPRITE_MCP_ROOT`, never against wherever Aseprite
happens to run, and `~` is expanded. Absolute paths are used as given unless the sandbox is
on, in which case anything outside the root (including through `..` or symlinks) is
refused.

Tools that write a new file (`export`, `save_copy`, ...) refuse to replace an existing one
unless you pass `overwrite: true`.

## Saving is atomic

Edits are written to a hidden temporary file next to the sprite and only replace it when
the whole run succeeded, so a failed or timed-out call leaves the original untouched.
Exports and other output files work the same way. The new file keeps the old one's
permissions, but it is a new file: hard links to the old one are not updated. A read-only
file is refused before anything runs.

## Size caps

Inputs are capped so a bad request ends with a clear error instead of a hung process.

| Limit | Value |
|---|---|
| Canvas | 4096 x 4096 |
| Points in one `draw_line` or `draw_polygon` | 4096 |
| `read_pixels` per call | `ASEPRITE_MCP_MAX_READ_PIXELS`, default 65536 |
| `check_animation` overlap scan | `ASEPRITE_MCP_MAX_SCAN_PIXELS`, default 16777216 |
| Ops in one `batch` | `ASEPRITE_MCP_MAX_BATCH_OPS`, default 1000 |
| `view_sprite` | up to 64 frames; at most 2048 px per side; default scale keeps the image within 512 px |
| `draw_text` | 2000 characters, 2048 x 2048 px |
| `run_lua` script | 200 KB |

Each Aseprite run also has a time limit, `ASEPRITE_TIMEOUT_SECONDS` (default 60).

## Results

`painted` in a drawing result counts the canvas pixels the op covered, including any the
colour left as they were (a transparent colour with `blend: true`). Read-only tools never
touch the file.
