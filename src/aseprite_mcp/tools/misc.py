from typing import Annotated, Any

from pydantic import BaseModel, Field

from .. import server
from ..paths import resolve_path
from ._registry import SpritePath, run_batch


class BatchItem(BaseModel):
    tool: str = Field(description="Name of a batchable tool, e.g. resize_sprite")
    args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments of that tool, without the path"
    )


@server.mcp.tool()
async def batch(
    path: SpritePath, ops: Annotated[list[BatchItem], Field(min_length=1)]
) -> list[dict[str, Any]]:
    """Run several single-step tools on one sprite in one go and return their results in order.

    The ops run in a single Aseprite process and are saved once at the end. If any op
    fails, nothing is saved and the error names the failing op. create_sprite and other
    multi-step tools are not accepted.
    """
    target = resolve_path(path, server.get_settings(), must_exist=True)
    return await run_batch(target, [(item.tool, item.args) for item in ops])
