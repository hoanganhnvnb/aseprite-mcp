from pathlib import Path

from .config import Settings
from .errors import ToolError


def resolve_path(p: str, s: Settings, *, must_exist: bool) -> Path:
    if not p.strip():
        raise ToolError("Path must not be empty")
    try:
        path = Path(p).expanduser()
        if not path.is_absolute():
            path = s.root / path
        path = path.resolve()
    except (RuntimeError, ValueError) as e:
        raise ToolError(f"Invalid path {p!r}: {e}") from e
    if s.sandbox and not path.is_relative_to(s.root.resolve()):
        raise ToolError(f"Path is outside the allowed root ({s.root}): {p}")
    if must_exist and not path.exists():
        raise ToolError(f"File not found: {path}")
    return path
