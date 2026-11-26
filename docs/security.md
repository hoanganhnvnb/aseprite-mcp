# Security

The server runs on your machine, as you, and opens files you or your assistant name. This
page lists what it guards and where the guarding stops.

## Sandbox

Off by default, because most setups run the server for one person on their own files.
Set `ASEPRITE_MCP_SANDBOX=1` to keep every read and write inside `ASEPRITE_MCP_ROOT`. A
path that resolves outside the root, including through `..` or symlinks, is refused.
The sandbox covers paths the server resolves for its tools; it is not an operating
system sandbox.

## run_lua

`run_lua` runs arbitrary Lua inside Aseprite, which can read and write any file and start
programs. It is only registered when `ASEPRITE_MCP_ALLOW_LUA=1`, and never in sandbox
mode (each call checks both again). Turn it on only in setups where you trust whatever
sends the script. Prefer the dedicated tools when one fits.

## Preview server

`start_preview` serves a folder over HTTP so you can watch an exported GIF.

- It binds to `127.0.0.1` only.
- URLs start with a random token; a request without it gets 404.
- The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`, so a web page that
  rebinds its own domain to your machine is refused (403).
- Only `.png`, `.gif`, `.webp`, `.bmp`, `.tga`, `.qoi` and `.json` files are served.
  Dotfiles, other files and anything outside the folder, symlinks included, answer 404.
  Nothing can be uploaded.
- One preview runs at a time, and it stops with the server.

## Atomic save

Every write goes to a temporary file first and replaces the target only when the whole
run succeeded, so a failed or timed-out call leaves the original untouched. A read-only
file is refused before anything runs. Tools that write a new file replace an existing one
only when you pass `overwrite: true`.

## Lock scope

Within one server process, calls on the same file (and on the files an op reads or
writes) run one after another. Separate server processes, or other programs, editing the
same file at the same time are not coordinated. Do not point two servers at the same
files, and close the file in the Aseprite editor while an assistant edits it.

## Limits

Input sizes are capped (canvas, point lists, reads, view size, text, script size, batch
length) and each Aseprite run has a timeout, so a bad request ends with a clear error. See
[concepts](concepts.md#size-caps).

## Reporting a problem

Report vulnerabilities privately through GitHub security advisories, not in a public
issue. See [SECURITY](../SECURITY.md).
