# Getting started

## What you need

- Python 3.12 or newer.
- Aseprite 1.3 or newer with Lua scripting (tested with 1.3.18, API 41). You need your
  own copy: a purchased build (Steam, itch.io, the official site) or one you compiled.
  This project is not affiliated with Aseprite or its authors.

## Install

Pick one. All three use the GitHub repository. `uvx` runs the server on demand without
a separate install step; `pipx` and `pip` install the `aseprite-mcp` command.

```sh
# uvx: fetch and run
uvx --from git+https://github.com/hoanganhnvnb/aseprite-mcp aseprite-mcp --check

# pipx: install the command
pipx install git+https://github.com/hoanganhnvnb/aseprite-mcp  # needs Python 3.12+

# pip: into a virtual environment
python -m venv .venv
.venv/bin/pip install git+https://github.com/hoanganhnvnb/aseprite-mcp
```

On Windows the pip command is `.venv\Scripts\pip`. Docker is not supported.

## Find Aseprite

The server looks for the executable in this order:

1. `ASEPRITE_PATH`. When it is set, it is the only place looked at, so a typo is
   reported instead of silently picking up another binary.
2. `aseprite` on `PATH`.
3. The usual install folders:
   - macOS: `/Applications/Aseprite.app`, then the Steam library folder
   - Windows: `%ProgramFiles%\Aseprite`, then Steam under `%ProgramFiles(x86)%`
   - Linux: Steam folders under your home, then `/usr/bin/aseprite`

If yours lives somewhere else, set `ASEPRITE_PATH` to the executable file.

## Check the setup

```sh
aseprite-mcp --check
```

It prints the root folder, sandbox state and timeout, finds Aseprite, runs a tiny script
in it and prints the version and API level. It exits with status 1 and a hint when
Aseprite is missing or cannot run scripts, and with status 2 when an environment variable
holds a value the server cannot use. `aseprite-mcp --version` prints the server version.

## Add it to a client

Most MCP clients take a `mcpServers` block in their JSON settings.

**macOS**, with `uvx` (on Linux the same block works; use your own paths, such as
`/usr/bin/aseprite`):

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/hoanganhnvnb/aseprite-mcp", "aseprite-mcp"],
      "env": {
        "ASEPRITE_PATH": "/Applications/Aseprite.app/Contents/MacOS/aseprite",
        "ASEPRITE_MCP_ROOT": "/Users/me/pixel-art"
      }
    }
  }
}
```

**Windows**, with `pipx` or `pip`: call the installed command and drop `args`:

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

Clients with a command-line way to add servers take the same command, arguments and
environment variables. `ASEPRITE_MCP_ROOT` is the folder that relative paths resolve
against; without it that is the folder the client starts the server in. Restart the
client after changing its settings. All variables are listed in
[configuration](configuration.md).

## First prompt

> Create a 32x32 sprite called `slime.aseprite`, draw a small green slime with a dark
> outline, then show it to me.

The assistant will typically call `create_sprite`, draw with `draw_ellipse` and
`draw_pixels`, add an `outline`, and look at the result with `view_sprite`. Open the file in
Aseprite afterwards: layers, frames and tags are all there.

Next: [concepts](concepts.md) for the conventions every tool shares, and
[batch](batch.md) for making many edits fast.
