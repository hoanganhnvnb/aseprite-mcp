from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt

from ..ranges import FrameSpec, parse_frames
from ._registry import op_tool

MAX_NEW_FRAMES = 512

DurationMs = Annotated[int, Field(ge=1, le=65535, description="Frame duration in milliseconds")]
FrameNumber = Annotated[StrictInt, Field(ge=1, description="1-based frame number")]
TagName = Annotated[str, Field(min_length=1, description="Tag name, matched exactly")]


@op_tool("add_frames", mutates=True)
def add_frames(
    count: Annotated[int, Field(ge=1, le=MAX_NEW_FRAMES, description="Frames to add")] = 1,
    after: Annotated[
        int | None,
        Field(ge=0, description="Insert after this frame; 0 inserts at the start, null appends"),
    ] = None,
    duration_ms: Annotated[
        int | None, Field(ge=1, le=65535, description="Duration of the new frames")
    ] = None,
    copy_content: Annotated[
        bool, Field(description="Copy the cels of the frame before the new ones")
    ] = False,
) -> dict[str, Any]:
    """Insert frames, empty unless copy_content is true. Returns the new frame numbers.

    copy_content copies every layer's cel of the frame before the new ones (the old first
    frame when after=0) as independent cels. Without duration_ms the new frames take the
    duration of that same frame.
    """
    return {
        "count": count,
        "after": after,
        "duration_ms": duration_ms,
        "copy_content": copy_content,
    }


@op_tool("delete_frames", mutates=True)
def delete_frames(frames: FrameSpec) -> dict[str, Any]:
    """Delete frames; later frames and tags move up. At least one frame must remain."""
    return {"frames": frames}


@op_tool("set_frame_duration", mutates=True)
def set_frame_duration(duration_ms: DurationMs, frames: FrameSpec = "all") -> dict[str, Any]:
    """Set how long frames are shown, in milliseconds."""
    return {"frames": frames, "duration_ms": duration_ms}


def _targets(targets: str | StrictInt) -> dict[str, Any]:
    if isinstance(targets, str) and targets.strip().lower().startswith("append:"):
        count = targets.split(":", 1)[1].strip()
        if not count.isdigit() or not 1 <= int(count) <= MAX_NEW_FRAMES:
            raise ValueError(f"invalid targets {targets!r}: append:N needs N from 1 to 512")
        return {"targets": None, "append": int(count)}
    return {"targets": parse_frames(targets), "append": None}


@op_tool("copy_frames", mutates=True)
def copy_frames(
    source: FrameNumber,
    targets: Annotated[
        str | StrictInt,
        Field(
            description='Frames to copy into ("2", "3-6", "all"), or "append:N" to add N '
            "empty frames at the end and copy into those"
        ),
    ],
    layers: Annotated[
        list[Annotated[str, Field(min_length=1)]] | None,
        Field(
            min_length=1,
            description="Layers to copy (a group means all layers in it); null for all",
        ),
    ] = None,
    mode: Annotated[
        Literal["replace", "missing_only"],
        Field(description="replace every target cel, or fill only where a layer has none"),
    ] = "replace",
    link: Annotated[bool, Field(description="Make the copies linked cels")] = False,
) -> dict[str, Any]:
    """Copy the cels of one frame into other frames, layers inside groups included.

    replace makes each target cel equal to the source: image, position, opacity and
    z-index, and a target is cleared where the source frame has no cel. missing_only only
    fills targets where the layer has no cel yet. link=true makes the copies linked cels
    that share the source's image. The source frame itself is skipped if listed in
    targets. Frame durations are not copied. A locked layer (or one in a locked group)
    that the copy would change is refused.

    Example: {"path": "hero.aseprite", "source": 1, "targets": "append:3"}
    """
    return {
        "source": source,
        **_targets(targets),
        "layers": layers,
        "mode": mode,
        "link": link,
    }


@op_tool("set_tag", mutates=True)
def set_tag(
    name: TagName,
    from_frame: FrameNumber,
    to_frame: FrameNumber,
    direction: Annotated[
        Literal["forward", "reverse", "pingpong", "pingpong_reverse"],
        Field(description="Playback direction of the tag"),
    ] = "forward",
    repeat: Annotated[
        int, Field(ge=0, le=65535, description="Times to play the tag; 0 loops forever")
    ] = 0,
) -> dict[str, Any]:
    """Create a tag over frames from_frame..to_frame, or update the tag with that name.

    If several tags share the name, the first one is updated.
    """
    if from_frame > to_frame:
        raise ValueError(f"from_frame {from_frame} is after to_frame {to_frame}")
    return {
        "name": name,
        "from_frame": from_frame,
        "to_frame": to_frame,
        "direction": direction,
        "repeat": repeat,
    }


@op_tool("delete_tag", mutates=True)
def delete_tag(name: TagName) -> dict[str, Any]:
    """Delete the tag with this exact name (the first one if several share it)."""
    return {"name": name}
