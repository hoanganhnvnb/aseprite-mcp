from mcp.server.fastmcp.exceptions import ToolError

__all__ = ["AsepriteError", "ToolError"]


class AsepriteError(Exception):
    """Aseprite exited with an error or produced unusable output."""
