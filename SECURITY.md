# Security policy

## Reporting a vulnerability

Please report it privately through GitHub security advisories: open the repository's
**Security** tab and choose **Report a vulnerability**. Do not open a public issue for a
security problem. Include what you did, what you expected and what happened, and the
version (`aseprite-mcp --version`).

## Scope

In scope:

- Reading or writing files outside the root while `ASEPRITE_MCP_SANDBOX=1`.
- `run_lua` being available without `ASEPRITE_MCP_ALLOW_LUA=1`, or in sandbox mode.
- The preview server answering requests it should refuse: a wrong token, a wrong `Host`
  header, dotfiles, other file types, or paths outside the served folder.
- A failed or interrupted call corrupting a sprite or replacing a file it should not.

Out of scope:

- Anything `run_lua` does when you enabled it; it runs arbitrary Lua by design.
- Access to files outside the root while the sandbox is off, which is the default.
- Vulnerabilities in Aseprite itself or in your MCP client. Report those to their
  authors.

How the safeguards work is described in [docs/security.md](docs/security.md).
