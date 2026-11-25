import argparse
import asyncio
import os
import sys

from . import __version__
from .config import ConfigError, Settings, load_settings
from .errors import AsepriteError
from .ops import run_op


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aseprite-mcp",
        description="MCP server for editing sprites with Aseprite. Without options it "
        "serves over stdio.",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument(
        "--check", action="store_true", help="check that Aseprite can be found and run"
    )
    return parser


def _check(settings: Settings) -> int:
    print(f"Root:     {settings.root}")
    print(f"Sandbox:  {'on' if settings.sandbox else 'off'}")
    print(f"Timeout:  {settings.timeout:g}s")
    if settings.aseprite is None:
        configured = os.environ.get("ASEPRITE_PATH", "").strip()
        if configured:
            hint = f"ASEPRITE_PATH is set to {configured!r} but no executable is there."
        else:
            hint = "Set ASEPRITE_PATH to the Aseprite executable or put it on PATH."
        print(f"Aseprite was not found. {hint}", file=sys.stderr)
        return 1
    print(f"Aseprite: {settings.aseprite}")
    try:
        info = asyncio.run(run_op(None, "_ping", {}, settings=settings, mutates=False))
    except (AsepriteError, OSError) as e:
        print(
            f"Aseprite could not run a script: {e}\nCheck that ASEPRITE_PATH points to a "
            "working Aseprite 1.3 or newer.",
            file=sys.stderr,
        )
        return 1
    print(f"Version:  {info['version']} (API {info['api']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    if args.version:
        print(f"aseprite-mcp {__version__}")
        return 0
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"aseprite-mcp: {e}", file=sys.stderr)
        return 2
    if args.check:
        return _check(settings)

    from .server import mcp

    mcp.run()
    return 0
