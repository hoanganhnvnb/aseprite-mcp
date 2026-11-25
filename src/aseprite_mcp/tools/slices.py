from typing import Annotated, Any

from pydantic import Field

from ..colors import parse_color
from ..models import Color, Point, Rect
from ._registry import op_tool

SliceName = Annotated[str, Field(min_length=1, max_length=256)]
Center = Annotated[
    Rect | None,
    Field(description="9-slice centre, relative to the slice's top-left; must fit inside it"),
]
Pivot = Annotated[Point | None, Field(description="Pivot point relative to the slice's top-left")]


def _check_center(center: Rect | None, rect: Rect | None) -> None:
    if center is None or rect is None:
        return
    if center.x < 0 or center.y < 0 or center.x + center.w > rect.w or center.y + center.h > rect.h:
        raise ValueError(
            f"center must lie inside the slice: a {rect.w}x{rect.h} slice cannot hold "
            f"{center.w}x{center.h} at ({center.x}, {center.y})"
        )


def _slice_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": result["name"],
        "bounds": result["bounds"],
        "center": result.get("center"),
        "pivot": result.get("pivot"),
        "color": result["color"],
        "data": result["data"],
    }


def _list_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return {"slices": [_slice_result(s, {}) for s in result.get("slices", [])]}


@op_tool("create_slice", mutates=True, finish=_slice_result)
def create_slice(
    name: SliceName,
    rect: Rect,
    center: Center = None,
    pivot: Pivot = None,
    color: Color | None = None,
) -> dict[str, Any]:
    """Add a named slice over rect (canvas pixels); names must be unique.

    The slice covers every frame (per-frame slice keys are not supported).
    """
    _check_center(center, rect)
    return {
        "name": name,
        "rect": rect.model_dump(),
        "center": center.model_dump() if center else None,
        "pivot": pivot.model_dump() if pivot else None,
        "color": list(parse_color(color)) if color else None,
    }


@op_tool("update_slice", mutates=True, finish=_slice_result)
def update_slice(
    name: SliceName,
    rect: Rect | None = None,
    center: Center = None,
    pivot: Pivot = None,
) -> dict[str, Any]:
    """Move or resize a slice, or set its 9-slice centre or pivot; other fields stay.

    A centre that no longer fits the new rect is an error.
    """
    if rect is None and center is None and pivot is None:
        raise ValueError("nothing to change: pass rect, center or pivot")
    _check_center(center, rect)
    return {
        "name": name,
        "rect": rect.model_dump() if rect else None,
        "center": center.model_dump() if center else None,
        "pivot": pivot.model_dump() if pivot else None,
    }


@op_tool("list_slices", mutates=False, finish=_list_result)
def list_slices() -> dict[str, Any]:
    """List the slices: name, bounds, 9-slice center, pivot, colour and user data.

    center and pivot are relative to the slice and null when not set.
    """
    return {}


@op_tool("delete_slice", mutates=True)
def delete_slice(name: SliceName) -> dict[str, Any]:
    """Delete the slice with this name."""
    return {"name": name}
