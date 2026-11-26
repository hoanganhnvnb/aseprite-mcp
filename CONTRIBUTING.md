# Contributing

Thanks for helping. Small, focused pull requests are easiest to review.

## Setup

```sh
git clone https://github.com/hoanganhnvnb/aseprite-mcp
cd aseprite-mcp
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

On Windows use `.venv\Scripts\` instead of `.venv/bin/`. You need Python 3.12 or newer.

## Tests

```sh
.venv/bin/pytest -m "not aseprite"
```

That runs everything that does not need the editor, and is what CI runs on Linux, macOS and
Windows. Tests marked `aseprite` drive a real Aseprite and are skipped when it cannot be
found. To run them, point `ASEPRITE_PATH` at your executable:

```sh
ASEPRITE_PATH=/path/to/aseprite .venv/bin/pytest
```

Layout: `tests/unit` for pure Python, `tests/integration` for tools against a real
Aseprite, `tests/lua` for the Lua scripts they run. A bug fix starts with a test that
fails without the fix.

`bench/bench.py` times a few common calls against a real Aseprite:
`ASEPRITE_PATH=/path/to/aseprite .venv/bin/python bench/bench.py`.

## Lint

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Use `ruff format .` to fix formatting. The line length is 100.

## Docs

`docs/tools.md` is generated from the tool registry. After you add or change a tool, its
parameters or its description, regenerate it and commit the result:

```sh
.venv/bin/python scripts/gen_tool_docs.py
```

`scripts/gen_tool_docs.py --check` fails when the file is stale, and a unit test does the
same. The other pages in `docs/` are written by hand; the docs tests also check links,
tool names and environment variables mentioned there.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), in English, short:
`type(scope): description`, for example `fix(layers): refuse merging a locked layer`.
One logical change per commit.

## Pull requests

Describe what changed and why, and say how you tested it. Keep unrelated changes out.
CI must pass.
