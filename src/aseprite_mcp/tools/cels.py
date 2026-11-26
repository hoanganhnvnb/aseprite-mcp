from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StrictInt

from ..ranges import FrameSpec
from ._registry import op_tool
from .layers import LayerRef
from .sprite import MAX_CANVAS

MAX_SCALE = 16
MIN_SCALE = 0.05
# Positions far outside any canvas are almost certainly a mistake.
MAX_OFFSET = 65535

Coord = Annotated[int, Field(ge=-MAX_OFFSET, le=MAX_OFFSET)]


class XY(BaseModel):
    """A pair of values for the x and y axes."""

    x: float = Field(ge=-MAX_OFFSET, le=MAX_OFFSET, allow_inf_nan=False)
    y: float = Field(ge=-MAX_OFFSET, le=MAX_OFFSET, allow_inf_nan=False)


TweenValue = Annotated[
    float | XY,
    Field(
        description="position: {x, y} cel position; opacity: 0..255; "
        "scale: a factor or {x, y} factors, 0.05..16"
    ),
]


def _at_least_two(frames: list[int] | str, tool: str) -> None:
    if frames != "all" and len(frames) < 2:
        raise ValueError(f"{tool} needs at least 2 frames")


@op_tool("set_cel", mutates=True)
def set_cel(
    layer: LayerRef,
    frames: FrameSpec,
    x: Annotated[Coord | None, Field(description="Cel left edge in sprite pixels")] = None,
    y: Annotated[Coord | None, Field(description="Cel top edge in sprite pixels")] = None,
    relative: Annotated[bool, Field(description="Move by x/y instead of moving to x/y")] = False,
    opacity: Annotated[int | None, Field(ge=0, le=255, description="Cel opacity, 0..255")] = None,
    z_index: Annotated[
        int | None,
        Field(ge=-32768, le=32767, description="Draw order offset against other layers' cels"),
    ] = None,
    create: Annotated[
        bool, Field(description="Create an empty cel where the layer has none")
    ] = False,
) -> dict[str, Any]:
    """Set the position, opacity and/or z-index of a layer's cels in the given frames.

    The position is the sprite coordinate of the cel image's top-left corner; an axis
    left out keeps its value. A frame without a cel is an error unless create is true,
    which adds an empty cel at (0, 0) first. Linked cels get their own copy before they
    move or fade, so frames outside the list never change. The layer must not be locked.
    The result lists the first 64 frames only; frames and created count all of them.
    """
    if x is None and y is None and opacity is None and z_index is None:
        raise ValueError("nothing to change: pass x, y, opacity or z_index")
    return {
        "layer": layer,
        "frames": frames,
        "x": x,
        "y": y,
        "relative": relative,
        "opacity": opacity,
        "z_index": z_index,
        "create": create,
    }


@op_tool("clear_cels", mutates=True)
def clear_cels(layer: LayerRef, frames: FrameSpec) -> dict[str, Any]:
    """Delete a layer's cels in the given frames; frames without a cel are skipped.

    Linked cels in other frames keep their image. Returns how many cels were removed.
    The layer must not be locked.
    """
    return {"layer": layer, "frames": frames}


def _pair(value: float | XY, name: str, low: float, high: float, what: str) -> list[float]:
    pair = [value.x, value.y] if isinstance(value, XY) else [value, value]
    for v in pair:
        if not low <= v <= high:
            raise ValueError(f"{what} {name} {v:g} is out of range: use {low:g} to {high:g}")
    return pair


def _tween_values(prop: str, start: float | XY, end: float | XY) -> tuple[Any, Any]:
    if prop == "position":
        if not isinstance(start, XY) or not isinstance(end, XY):
            raise ValueError('position needs start and end as {"x": ..., "y": ...}')
        return [start.x, start.y], [end.x, end.y]
    if prop == "opacity":
        if isinstance(start, XY) or isinstance(end, XY):
            raise ValueError("opacity needs start and end as numbers from 0 to 255")
        _pair(start, "start", 0, 255, "opacity")
        _pair(end, "end", 0, 255, "opacity")
        return start, end
    return (
        _pair(start, "start", MIN_SCALE, MAX_SCALE, "scale"),
        _pair(end, "end", MIN_SCALE, MAX_SCALE, "scale"),
    )


@op_tool("tween_cels", mutates=True)
def tween_cels(
    layer: LayerRef,
    frames: FrameSpec,
    property: Annotated[
        Literal["position", "opacity", "scale"], Field(description="What to animate")
    ],
    start: TweenValue,
    end: TweenValue,
    easing: Annotated[
        Literal["linear", "ease_in", "ease_out", "ease_in_out", "ease_out_back", "bounce"],
        Field(description="How the value moves from start to end"),
    ] = "linear",
    source_frame: Annotated[
        StrictInt | None,
        Field(ge=1, description="scale only: frame whose cel is scaled; default first frame"),
    ] = None,
    anchor: Annotated[
        Literal["center", "bottom", "top_left"],
        Field(description="scale only: point of the cel that stays in place"),
    ] = "center",
    loop: Annotated[
        bool, Field(description="Stop one step before end so a looping animation stays smooth")
    ] = False,
) -> dict[str, Any]:
    """Animate a layer's cels from start to end across the frames, in frame order.

    position: start/end are {x, y} absolute cel positions (top-left of the cel image in
    sprite coordinates). opacity: numbers 0..255. scale: a factor, or {x, y} factors,
    0.05..16 of the source_frame cel, resized nearest-neighbour around the anchor and
    written as a new cel in every frame (created where missing). position and opacity
    need a cel in every frame. Values round to the nearest integer, halves away from
    zero. Needs at least 2 frames; frame i of n gets t = i/(n-1), or i/n with loop.
    easing: ease_in t², ease_out 1-(1-t)², ease_in_out quadratic in/out,
    ease_out_back overshoots past end then settles, bounce bounces into end.
    Eased scale factors are clamped to 0.05..16. scale places every cel from the source
    cel's position, replacing earlier position tweens. The result lists the first 64
    frames only. The layer must not be locked.
    """
    _at_least_two(frames, "tween_cels")
    if source_frame is not None and property != "scale":
        raise ValueError("source_frame only applies to property='scale'")
    first, last = _tween_values(property, start, end)
    return {
        "layer": layer,
        "frames": frames,
        "property": property,
        "start": first,
        "end": last,
        "easing": easing,
        "source_frame": source_frame,
        "anchor": anchor,
        "loop": loop,
        "max_size": MAX_CANVAS,
    }


Amplitude = Annotated[float, Field(ge=-4096, le=4096, allow_inf_nan=False)]


@op_tool("oscillate_cels", mutates=True)
def oscillate_cels(
    layer: LayerRef,
    frames: FrameSpec,
    amplitude_x: Annotated[Amplitude, Field(description="Horizontal swing in pixels")] = 0,
    amplitude_y: Annotated[Amplitude, Field(description="Vertical swing in pixels")] = 0,
    cycles: Annotated[
        float, Field(ge=0.1, le=64, description="Full waves across the frames")
    ] = 1.0,
    phase: Annotated[
        float, Field(ge=-64, le=64, allow_inf_nan=False, description="Offset in cycles")
    ] = 0.0,
) -> dict[str, Any]:
    """Swing a layer's cels along a sine wave across the frames (a bob or sway loop).

    Frame i of n is placed at base + amplitude * sin(2π(cycles * i/n + phase)), rounded,
    so the last frame leads back into the first only when cycles is a whole number. The base is chosen so the first frame
    keeps its current position: running the tool again with the same arguments gives
    the same result. An axis with amplitude 0 is left as it is. Every frame needs a cel.
    The result lists the first 64 frames only. The layer must not be locked.
    """
    _at_least_two(frames, "oscillate_cels")
    if amplitude_x == 0 and amplitude_y == 0:
        raise ValueError("nothing to do: set amplitude_x or amplitude_y")
    return {
        "layer": layer,
        "frames": frames,
        "amplitude_x": amplitude_x,
        "amplitude_y": amplitude_y,
        "cycles": cycles,
        "phase": phase,
    }
