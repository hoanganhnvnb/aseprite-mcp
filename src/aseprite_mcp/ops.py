from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .runner import LUA_DIR, run_script

MAIN_SCRIPT = LUA_DIR / "main.lua"


@dataclass
class Op:
    name: str
    params: dict[str, Any]
    mutates: bool


def op_files() -> list[str]:
    return sorted(p.name for p in (LUA_DIR / "ops").glob("*.lua"))


async def run_ops(
    path: Path | None,
    ops: list[Op],
    *,
    settings: Settings,
    create: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run ops in one Aseprite process; with `create`, a new sprite is saved to `path`."""
    if create is not None and path is None:
        raise ValueError("create needs a target path")
    saves = create is not None or any(op.mutates for op in ops)
    params = {
        "ops": [{"name": op.name, "params": op.params, "mutates": op.mutates} for op in ops],
        "op_files": op_files(),
        "create": create,
        "target": str(path) if path is not None else None,
    }
    result = await run_script(
        MAIN_SCRIPT,
        params,
        settings=settings,
        lock_paths=[path] if path is not None else (),
        open_file=path if create is None else None,
        save_to=path if saves else None,
    )
    # Aseprite's json.encode writes an empty table as [], so an op that returns
    # an empty object comes back as a list.
    return [r if r != [] else {} for r in result.data.get("results", [])]


async def run_op(
    path: Path | None,
    name: str,
    params: dict[str, Any],
    *,
    settings: Settings,
    mutates: bool,
) -> dict[str, Any]:
    results = await run_ops(path, [Op(name, params, mutates)], settings=settings)
    return results[0]
