import functools
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import AsepriteError
from .runner import (
    LUA_DIR,
    check_writable,
    remove_temp_files,
    replace_file,
    run_script,
    temp_sibling,
)

MAIN_SCRIPT = LUA_DIR / "main.lua"
OPS_DIR = LUA_DIR / "ops"

_OP_DEFINITION = re.compile(r"^OPS\.(\w+)\s*=", re.MULTILINE)
# run_lua scripts can call any op through OPS, so it gets every op file.
_NEEDS_ALL_OPS = {"run_lua"}


@dataclass
class Op:
    name: str
    params: dict[str, Any]
    mutates: bool
    # Shown in error messages instead of the op name, e.g. the tool that built it.
    label: str | None = None
    # Files the op writes besides the sprite, as (temporary, final) pairs. The op
    # writes the temporary file; it is moved into place only if the whole run succeeds.
    writes: list[tuple[Path, Path]] = field(default_factory=list)
    # Other sprites the op opens for reading; locked like the sprite for the run.
    reads: list[Path] = field(default_factory=list)


def output_file(final: Path) -> tuple[Path, Path]:
    return temp_sibling(final), final


@functools.cache
def op_owners() -> dict[str, str]:
    """Op name -> the file in lua/ops that defines it."""
    owners = {}
    for path in sorted(OPS_DIR.glob("*.lua")):
        for name in _OP_DEFINITION.findall(path.read_text(encoding="utf-8")):
            owners[name] = path.name
    return owners


def op_files(names: Iterable[str]) -> list[str]:
    """The op files a run of these ops has to load; unknown names need none."""
    owners = op_owners()
    wanted = set(names)
    if wanted & _NEEDS_ALL_OPS:
        return sorted(set(owners.values()))
    return sorted({owners[name] for name in wanted if name in owners})


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
    writes = [pair for op in ops for pair in op.writes]
    params = {
        "ops": [
            {"name": op.name, "label": op.label, "params": op.params, "mutates": op.mutates}
            for op in ops
        ],
        "op_files": op_files(op.name for op in ops),
        "create": create,
        "target": str(path) if path is not None else None,
    }
    lock_paths = [final for _, final in writes]
    lock_paths += [source for op in ops for source in op.reads]
    if path is not None:
        lock_paths.append(path)
    for _, final in writes:
        check_writable(final)
    try:
        result = await run_script(
            MAIN_SCRIPT,
            params,
            settings=settings,
            lock_paths=lock_paths,
            open_file=path if create is None else None,
            save_to=path if saves else None,
        )
        for tmp, final in writes:
            if not tmp.is_file():
                raise AsepriteError(f"Aseprite could not write {final}")
            replace_file(tmp, final)
    finally:
        for tmp, _ in writes:
            remove_temp_files(tmp)
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
