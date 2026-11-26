## What and why

## How I tested it

- [ ] `ruff check .` and `ruff format --check .`
- [ ] `pytest -m "not aseprite"`
- [ ] Tests that need Aseprite, if the change touches a tool
- [ ] `python scripts/gen_tool_docs.py` run if a tool changed
