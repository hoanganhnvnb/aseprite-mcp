# Troubleshooting

Start with `aseprite-mcp --check`; it reports most setup problems in plain words.

## Setup

**"Aseprite was not found."**
Set `ASEPRITE_PATH` to the executable file, or put `aseprite` on `PATH`. If
`ASEPRITE_PATH` is already set, the message says so: nothing is at that path, and the server
does not fall back to another binary. On macOS the executable is inside the app bundle
(`Aseprite.app/Contents/MacOS/aseprite`).

**"Aseprite could not run a script."**
The binary starts but cannot run Lua, or is older than 1.3. Use a build with scripting
enabled, version 1.3 or newer.

**The server exits at startup with a message naming a variable.**
A value is not usable: a flag that is not yes/no, a number outside its range. Fix it as
the message says; see [configuration](configuration.md).

**The client shows no tools.**
Run the same command from a terminal. A `uvx` or `pipx` command that works there but not in
the client usually means the client cannot find it on its `PATH`; use the full path to the
command.

## Calls

**"Path is outside the allowed root".**
The sandbox is on and the path resolves outside `ASEPRITE_MCP_ROOT`. Use a path inside it
or turn the sandbox off.

**"File not found".**
Relative paths resolve against `ASEPRITE_MCP_ROOT`, which is the server's working
directory when unset. Set it explicitly in the client configuration.

**"... already exists; pass overwrite=true to replace it".**
Tools that write a new file never replace one silently.

**"... is locked; unlock it first".**
The layer or a parent group is locked. Unlock it with `update_layer`.

**"a .png file holds a single flat layer but the sprite would have N layers".**
Flat formats cannot store layers, tilemaps, tags or slices. Work in an `.aseprite` file
(`save_copy` makes one), or `flatten_sprite` first. See
[concepts](concepts.md#file-formats).

**"Aseprite timed out after Ns and was killed".**
Raise `ASEPRITE_TIMEOUT_SECONDS`, or split the work. Nothing was saved.

**"op 3 (draw_rect): ..." from a batch.**
Op 3 failed and nothing was saved. See [batch](batch.md).

**"... is read-only; make it writable first".**
Nothing was changed. Fix the file's permissions.

**"run_lua is disabled".**
Start the server with `ASEPRITE_MCP_ALLOW_LUA=1` and without the sandbox. See
[security](security.md#run_lua).

**"This bitmap font has no glyph for: ...".**
Use a TrueType font for those characters, or remove them. See [fonts](fonts.md).

## Preview

**The preview URL gives 404.**
Open the URL exactly as returned, with its token. Only image and `.json` files are served,
and dotfiles are not.

**The preview URL gives 403.**
Use `127.0.0.1` or `localhost` with the port in the URL, not another host name.

## Still stuck

Open an issue with the output of `aseprite-mcp --check`, your client, and the failing call.
For anything security related use [SECURITY](../SECURITY.md) instead.
