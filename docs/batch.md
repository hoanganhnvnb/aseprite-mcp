# Batch

Every tool call starts one Aseprite process. `batch` runs several single-step tools on one
sprite in a single process and saves once at the end, so a long series of small edits costs
about one call instead of many.

If any op fails, nothing is saved and the error names the op (`op 3 (draw_rect): ...`).

## Shape of a call

`path` is the sprite; each op is `{"tool": ..., "args": {...}}` with the arguments of that
tool **without** `path`:

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

## Rules

- Ops run in order, in one process, so a later op sees the result of an earlier one.
- A call takes up to 1000 ops by default (`ASEPRITE_MCP_MAX_BATCH_OPS`, at most 100000).
- Arguments are validated like a direct call, except that an argument the tool does not
  have is an error in a batch.
- Only tools marked **batchable** in [tools](tools.md) are accepted. `create_sprite`,
  `view_sprite` and other tools that need more than one step are not; the error lists the
  ones that are. Create the sprite first, then batch.
- Two ops that write the same output file are refused.
- The batch is locked and saved like any other edit, see [concepts](concepts.md#saving-is-atomic).
- Results come back as a list, one entry per op, in order.

## When to use it

Drawing a sprite pixel by pixel, adding a dozen layers, or setting up frames and tags are
all good fits. The descriptions of tools that tend to be called many times in a row end with a
reminder to batch.
