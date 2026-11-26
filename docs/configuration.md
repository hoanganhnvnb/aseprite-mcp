# Configuration

Everything is set through environment variables, usually in the `env` block of the client
configuration (see [getting started](getting-started.md#add-it-to-a-client)).

| Variable | Default | Meaning |
|---|---|---|
| `ASEPRITE_PATH` | autodetect | Aseprite executable. When set it is the only place looked at |
| `ASEPRITE_MCP_ROOT` | the server's working directory | Folder that relative paths resolve against |
| `ASEPRITE_MCP_SANDBOX` | off | On refuses any path outside the root, and disables `run_lua` |
| `ASEPRITE_TIMEOUT_SECONDS` | `60` | Time limit for one Aseprite run, 1 to 3600 |
| `ASEPRITE_MCP_MAX_PROCS` | CPU count, at most 4 | Aseprite processes allowed at once, 1 to 32 |
| `ASEPRITE_MCP_ALLOW_LUA` | off | On adds the `run_lua` tool (ignored in sandbox mode) |
| `ASEPRITE_MCP_MAX_READ_PIXELS` | `65536` | Most pixels `read_pixels` returns per call, up to 16777216 |
| `ASEPRITE_MCP_MAX_SCAN_PIXELS` | `16777216` | Most pixels `check_animation` scans for overlaps, up to 2^30 |
| `ASEPRITE_MCP_MAX_BATCH_OPS` | `1000` | Most ops one `batch` call accepts, up to 100000 |
| `ASEPRITE_MCP_FONT_DIRS` | none | Extra font folders for `draw_text`, separated like `PATH`; a folder with an Aseprite `fonts.xml` adds its pixel fonts |

## Value rules

- Flags accept `1`, `true`, `yes` or `on` and `0`, `false`, `no` or `off`, in any case. An
  empty value means the default.
- Any other value, or a number outside its range, stops the server at startup with a
  message naming the variable. `aseprite-mcp --check` shows the same message and exits with
  status 2.
- Paths accept `~`. `ASEPRITE_MCP_FONT_DIRS` is split like `PATH`: `:` on Linux and macOS,
  `;` on Windows.

## Process limits

Calls on the same file run one after another. Calls on different files run in parallel, up
to `ASEPRITE_MCP_MAX_PROCS` Aseprite processes at a time; the rest wait. Raise the timeout
for very large sprites or long batches.
