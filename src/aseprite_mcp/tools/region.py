from typing import Annotated, Any, Literal

from pydantic import Field

from ..models import Coord, Rect
from ..ranges import FrameSpec
from ._registry import op_tool
from .layers import LayerRef

FrameNumber = Annotated[int, Field(ge=1, description="1-based frame number")]
Offset = Annotated[Coord, Field(description="Pixels to move by; negative goes left or up")]
WholeSprite = Annotated[
    LayerRef | None,
    Field(description="Layer name or 'group/child' path; leave out for every layer"),
]


@op_tool("move_region", mutates=True)
def move_region(
    layer: LayerRef,
    rect: Rect,
    dx: Offset,
    dy: Offset,
    frame: FrameNumber = 1,
    copy: Annotated[bool, Field(description="Leave the source pixels where they are")] = False,
    target_layer: Annotated[
        LayerRef | None, Field(description="Layer to put the pixels on; default the same layer")
    ] = None,
    target_frame: Annotated[
        int | None, Field(ge=1, description="Frame to put the pixels in; default the same frame")
    ] = None,
    blend: Annotated[
        bool,
        Field(
            description="false: the moved block replaces what is under it, transparent "
            "pixels included; true: it is alpha-blended over it"
        ),
    ] = False,
) -> dict[str, Any]:
    """Move (or with copy, duplicate) the pixels of a layer inside rect by (dx, dy).

    rect is in canvas coordinates and is clipped to the canvas first; outside its cel
    the layer counts as transparent. The source area is cleared unless copy is true,
    then the block is drawn at the destination, so overlapping moves work. Pixels whose
    destination is off the canvas are dropped and counted in clipped. With target_layer
    or target_frame the block lands there (the cel is created or grown as needed).
    Indexed and grayscale pixel values are copied as they are. A background layer
    stays opaque: its cleared source turns black and a block from another layer is
    blended onto it. Linked cels get their own copy first, so other frames never
    change.
    """
    if dx == 0 and dy == 0 and target_layer is None and target_frame is None:
        raise ValueError("nothing to move: dx and dy are 0 and the target is the source")
    return {
        "layer": layer,
        "rect": rect.model_dump(),
        "dx": dx,
        "dy": dy,
        "frame": frame,
        "copy": copy,
        "target_layer": target_layer,
        "target_frame": target_frame,
        "blend": blend,
    }


@op_tool("erase_region", mutates=True)
def erase_region(layer: LayerRef, rect: Rect, frames: FrameSpec = 1) -> dict[str, Any]:
    """Make the pixels of a layer inside rect transparent in each of the frames.

    On the background layer, which cannot be transparent, they turn opaque black.
    Cel content beyond the canvas edge inside rect is erased too. Frames where the
    layer has no cel are skipped and counted. Linked cels in other frames keep their
    pixels.
    """
    return {"layer": layer, "rect": rect.model_dump(), "frames": frames}


@op_tool("flip", mutates=True)
def flip(
    axis: Literal["horizontal", "vertical"],
    layer: WholeSprite = None,
    frames: FrameSpec = "all",
) -> dict[str, Any]:
    """Mirror a layer, or every layer, across the canvas centre.

    horizontal mirrors left and right: pixel x goes to width - 1 - x, whatever the
    cel's size and position, and cel content beyond the canvas edge is mirrored along.
    Without a layer every image layer is flipped, nested ones included; this is refused
    when any of them is locked or a tilemap. Linked cels are flipped once when all
    their frames are in the list and get their own copy otherwise. Slices are not
    moved.
    """
    return {"axis": axis, "layer": layer, "frames": frames}


@op_tool("rotate", mutates=True)
def rotate(
    angle: Annotated[Literal[90, 180, 270], Field(description="Degrees clockwise")],
    layer: WholeSprite = None,
    frames: FrameSpec = "all",
) -> dict[str, Any]:
    """Turn the whole sprite, or one layer, clockwise by 90, 180 or 270 degrees.

    Without a layer the canvas turns too (90 and 270 swap width and height) along with
    every layer in every frame; frames must then cover all frames. With a layer its
    cels turn about the canvas centre and the canvas keeps its size: on a non-square
    canvas, content that ends up off the canvas stays in the cel. With
    ox = floor((w - h) / 2) and oy = floor((h - w) / 2), 90 maps pixel (x, y) to
    (ox + h - 1 - y, oy + x) and 270 maps it to (y - oy, oy + w - 1 - x): an odd w - h
    rounds the half pixel of a 90 turn towards the top-left and 270 undoes 90 exactly.
    A background layer turns by 90/270 only on a square canvas. Slices are not moved.
    """
    return {"angle": angle, "layer": layer, "frames": frames}
