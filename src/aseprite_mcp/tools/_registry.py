import functools
import inspect
import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from .. import server
from ..errors import ToolError
from ..ops import Op, output_file, run_ops
from ..paths import check_save_extension, resolve_path

Builder = Callable[..., dict[str, Any]]
# Turns the op's raw result into the tool result; gets the result and the op params.
Finisher = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

SpritePath = Annotated[
    str,
    Field(description="Sprite file. Relative paths resolve against the server root."),
]

# tool name -> (op name, mutates, builder)
BATCHABLE: dict[str, tuple[str, bool, Builder]] = {}


@dataclass(frozen=True)
class _Extra:
    path_arg: str
    writes: str | None
    args_model: type[BaseModel]
    finish: Finisher | None


def _args_model(name: str, signature: inspect.Signature) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for param in signature.parameters.values():
        annotation = Any if param.annotation is param.empty else param.annotation
        default = ... if param.default is param.empty else param.default
        fields[param.name] = (annotation, default)
    # Tool parameters may share a name with a BaseModel method (move_region's `copy`);
    # the field wins on instances, which is all the batch validation needs.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r'Field name ".*" in ".*" shadows an attribute', category=UserWarning
        )
        return create_model(
            f"{name}_args",
            __config__=ConfigDict(extra="forbid", arbitrary_types_allowed=True),
            **fields,
        )


_EXTRA: dict[str, _Extra] = {}


def op_tool(
    op: str,
    *,
    mutates: bool,
    path_arg: str = "path",
    writes: str | None = None,
    finish: Finisher | None = None,
) -> Callable[[Builder], Callable[..., Any]]:
    """Register a tool that maps to exactly one Lua op.

    The decorated function receives the tool arguments except `path_arg` and returns
    the op params. The registered tool takes `path_arg` first, then the function's own
    parameters, so the schema comes from the function's signature and docstring.
    `writes` names a param holding an output path as the user gave it. The registry
    resolves it like any path, checks the folder, the extension and the builder's
    `overwrite` argument (False when it has none), and the op writes to a temporary
    file that replaces the output only when the whole run succeeds.
    `finish` reshapes the op's result in Python, in direct calls and in batch alike.
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
            built = make_op(name, builder(**kwargs), path, kwargs.get("overwrite", False))
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
        BATCHABLE[name] = (op, mutates, builder)
        _EXTRA[name] = _Extra(path_arg, writes, _args_model(name, signature), finish)
        return tool

    return register


def _same_file(a: Path, b: Path) -> bool:
    if os.path.normcase(a) == os.path.normcase(b):
        return True
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def _output_path(key: str, value: Any, overwrite: bool, sprite: Path) -> Path:
    final = resolve_path(str(value), server.get_settings(), must_exist=False)
    if _same_file(final, sprite):
        raise ToolError(f"{key} must be a different file than the sprite itself")
    if final.is_dir():
        raise ToolError(f"{final} is a folder")
    if not final.parent.is_dir():
        raise ToolError(f"Folder does not exist: {final.parent}")
    check_save_extension(final)
    if final.exists() and not overwrite:
        raise ToolError(f"{final} already exists; pass overwrite=true to replace it")
    return final


def make_op(tool: str, params: dict[str, Any], path: Path, overwrite: bool = False) -> Op:
    op, mutates, _ = BATCHABLE[tool]
    params = dict(params)
    writes = []
    key = _EXTRA[tool].writes
    if key is not None:
        tmp, final = output_file(_output_path(key, params[key], overwrite, path))
        params[key] = str(tmp)
        writes.append((tmp, final))
    return Op(op, params, mutates, label=tool, writes=writes)


def op_result(tool: str, op: Op, result: dict[str, Any]) -> dict[str, Any]:
    extra = _EXTRA[tool]
    if extra.finish is not None:
        result = extra.finish(result, op.params)
    key = extra.writes
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
        model = _EXTRA[tool].args_model.model_validate(args)
        valid = {name: getattr(model, name) for name in type(model).model_fields}
        return make_op(tool, builder(**valid), path, valid.get("overwrite", False))
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
    seen: dict[str, int] = {}
    for i, op in enumerate(built, 1):
        for _, final in op.writes:
            key = os.path.normcase(final)
            if key in seen:
                first = seen[key]
                raise ToolError(
                    f"op {first} ({entries[first - 1][0]}) and op {i} ({entries[i - 1][0]}) "
                    f"both write {final}"
                )
            seen[key] = i
    results = await run_ops(path, built, settings=server.get_settings())
    return [op_result(tool, op, r) for (tool, _), op, r in zip(entries, built, results)]
