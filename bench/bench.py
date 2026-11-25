"""Latency of a few common tool calls against a real Aseprite.

Usage:
    ASEPRITE_PATH=/path/to/aseprite python bench/bench.py [--runs 5]

Each scenario calls the tools through the server's own tool manager (argument
validation, path resolution, the Aseprite run and result handling all included),
in a temporary folder that is removed afterwards. Setup work is not timed. The
table shows the median wall time of each scenario in milliseconds.
"""

import argparse
import asyncio
import os
import random
import statistics
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

Call = Callable[..., Awaitable[Any]]


async def create_and_draw(call: Call, run: int) -> Callable[[], Awaitable[None]]:
    rng = random.Random(run)
    pixels = [
        {"x": rng.randrange(64), "y": rng.randrange(64), "color": f"#{rng.randrange(1 << 24):06x}"}
        for _ in range(2000)
    ]
    path = f"draw-{run}.aseprite"

    async def timed() -> None:
        await call("create_sprite", path=path, width=64, height=64)
        await call("draw_pixels", path=path, pixels=pixels)

    return timed


async def flip_layer(call: Call, run: int) -> Callable[[], Awaitable[None]]:
    path = f"flip-{run}.aseprite"
    await call("create_sprite", path=path, width=256, height=256)
    await call(
        "draw_rect",
        path=path,
        rect={"x": 0, "y": 0, "w": 160, "h": 200},
        color="#3366cc",
        fill=True,
    )

    async def timed() -> None:
        await call("flip", path=path, axis="horizontal", frames=1)

    return timed


async def copy_frames(call: Call, run: int) -> Callable[[], Awaitable[None]]:
    path = f"copy-{run}.aseprite"
    await call("create_sprite", path=path, width=64, height=64)
    await call(
        "draw_rect", path=path, rect={"x": 8, "y": 8, "w": 48, "h": 48}, color="#cc3333", fill=True
    )
    await call("add_frames", path=path, count=23)

    async def timed() -> None:
        await call("copy_frames", path=path, source=1, targets="2-24")

    return timed


async def read_pixels(call: Call, run: int) -> Callable[[], Awaitable[None]]:
    path = f"read-{run}.aseprite"
    await call("create_sprite", path=path, width=64, height=64)
    await call(
        "draw_rect", path=path, rect={"x": 4, "y": 4, "w": 40, "h": 50}, color="#22aa55", fill=True
    )

    async def timed() -> None:
        await call("read_pixels", path=path, rect={"x": 0, "y": 0, "w": 64, "h": 64})

    return timed


async def view_frames(call: Call, run: int) -> Callable[[], Awaitable[None]]:
    path = f"view-{run}.aseprite"
    await call("create_sprite", path=path, width=64, height=64)
    await call("draw_ellipse", path=path, cx=32, cy=32, rx=20, ry=14, color="#ddaa22", fill=True)
    await call("add_frames", path=path, count=7, copy_content=True)

    async def timed() -> None:
        await call("view_sprite", path=path, frames="1-8")

    return timed


SCENARIOS = [
    ("create 64x64 + draw 2000 pixels", create_and_draw),
    ("flip a 256x256 layer", flip_layer),
    ("copy frame 1 to frames 2-24", copy_frames),
    ("read 64x64 pixels", read_pixels),
    ("view 8 frames", view_frames),
]


async def bench(folder: Path, runs: int) -> list[tuple[str, float]]:
    # Settings are read once from the environment, so the root must be set first.
    os.environ["ASEPRITE_MCP_ROOT"] = str(folder)
    from aseprite_mcp.server import get_settings, mcp

    if get_settings().aseprite is None:
        sys.exit("Aseprite not found: set ASEPRITE_PATH")

    async def call(name: str, /, **args: Any) -> Any:
        return await mcp.call_tool(name, args)

    rows = []
    for label, setup in SCENARIOS:
        times = []
        for run in range(runs):
            timed = await setup(call, run)
            start = time.perf_counter()
            await timed()
            times.append((time.perf_counter() - start) * 1000)
        rows.append((label, statistics.median(times)))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5, help="runs per scenario (default 5)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="aseprite-mcp-bench-") as tmp:
        rows = asyncio.run(bench(Path(tmp).resolve(), max(1, args.runs)))

    width = max(len(label) for label, _ in rows)
    print(f"{'scenario':<{width}}  median ms")
    print(f"{'-' * width}  ---------")
    for label, ms in rows:
        print(f"{label:<{width}}  {ms:9.1f}")


if __name__ == "__main__":
    main()
