from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

__all__ = ["AsepriteError", "ToolError", "describe_invalid"]


class AsepriteError(Exception):
    """Aseprite exited with an error or produced unusable output."""


def describe_invalid(error: ValidationError) -> str:
    """The problems joined by "; ", without pydantic's input dump and help links."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'args'}: {err['msg']}"
        for err in error.errors()
    )
