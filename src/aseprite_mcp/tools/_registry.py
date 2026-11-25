import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, validate_call

from .. import server
from ..errors import ToolError
from ..ops import Op, output_file, run_ops
from ..paths import resolve_path

Builder = Callable[..., dict[str, Any]]

SpritePath = Annotated[
    str,
    Field(description="Sprite file. Relative paths resolve against the server root."),
]

# tool name -> (op name, mutates, builder); the builder validates its arguments.
BATCHABLE: dict[str, tuple[str, bool, Builder]] = {}


@dataclass(frozen=True)
class _Extra:
    path_arg: str
    writes: str | None


_EXTRA: dict[str, _Extra] = {}


def op_tool(
    op: str, *, mutates: bool, path_arg: str = "path", writes: str | None = None
) -> Callable[[Builder], Callable[..., Any]]:
    """Register a tool that maps to exactly one Lua op.

    The decorated function receives the tool arguments except `path_arg` and returns
    the op params. The registered tool takes `path_arg` first, then the function's own
    parameters, so the schema comes from the function's signature and docstring.
    `writes` names a param holding an absolute output path: the op writes to a
    temporary file that replaces the output only when the whole run succeeds.
    """

    def register(builder: Builder) -> Callable[..., Any]:
        name = builder.__name__
        signature = inspect.signature(builder, eval_str=True)
        if path_arg in signature.parameters:
            raise TypeError(f"{name}: '{path_arg}' is added by op_tool, do not declare it")

        @functools.wraps(builder)
        async def tool(**kwargs: Any) -> dict[str, Any]:
            settings = server.get_settings()
            path = resolve_path(kwargs.pop(path_arg), settings, must_exist=True)
            built = make_op(name, builder(**kwargs), path)
            [result] = await run_ops(path, [built], settings=settings)
            return op_result(name, built, result)

        path_param = inspect.Parameter(
            path_arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=SpritePath
        )
        tool.__signature__ = signature.replace(  # type: ignore[attr-defined]
            parameters=[path_param, *signature.parameters.values()],
            return_annotation=dict[str, Any],
        )
        server.mcp.add_tool(tool, name=name)
        BATCHABLE[name] = (op, mutates, validate_call(builder))
        _EXTRA[name] = _Extra(path_arg, writes)
        return tool

    return register


def make_op(tool: str, params: dict[str, Any], path: Path) -> Op:
    op, mutates, _ = BATCHABLE[tool]
    params = dict(params)
    writes = []
    key = _EXTRA[tool].writes
    if key is not None:
        tmp, final = output_file(Path(params[key]))
        if final == path:
            raise ToolError(f"{key} must be a different file than the sprite itself")
        params[key] = str(tmp)
        writes.append((tmp, final))
    return Op(op, params, mutates, label=tool, writes=writes)


def op_result(tool: str, op: Op, result: dict[str, Any]) -> dict[str, Any]:
    key = _EXTRA[tool].writes
    if key is None:
        return result
    return {**result, key: str(op.writes[0][1])}


def batch_op(index: int, tool: str, args: dict[str, Any], path: Path) -> Op:
    """Build the op for one batch entry, validating `args` like a direct call."""
    if tool not in BATCHABLE:
        allowed = ", ".join(sorted(BATCHABLE))
        raise ToolError(f"op {index}: {tool!r} cannot be used in batch; batchable tools: {allowed}")
    path_arg = _EXTRA[tool].path_arg
    if path_arg in args:
        raise ToolError(
            f"op {index} ({tool}): remove '{path_arg}' from args, the batch path applies to all ops"
        )
    builder = BATCHABLE[tool][2]
    try:
        return make_op(tool, builder(**args), path)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or 'args'}: {err['msg']}"
            for err in e.errors()
        )
        raise ToolError(f"op {index} ({tool}): invalid arguments: {problems}") from None
    except (ToolError, ValueError) as e:
        raise ToolError(f"op {index} ({tool}): {e}") from None


async def run_batch(path: Path, entries: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    built = [batch_op(i, tool, args, path) for i, (tool, args) in enumerate(entries, 1)]
    results = await run_ops(path, built, settings=server.get_settings())
    return [op_result(tool, op, r) for (tool, _), op, r in zip(entries, built, results)]
