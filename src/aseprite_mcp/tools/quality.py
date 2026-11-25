from typing import Annotated, Any, Literal

from pydantic import Field

from .. import server
from ..ranges import FrameSpec
from ._registry import op_tool
from .layers import LayerRef

MAX_FINDINGS = 200
MAX_NAMES = 256

LayerList = Annotated[list[LayerRef] | None, Field(max_length=MAX_NAMES)]
FrameRanges = Annotated[
    dict[str, FrameSpec] | None,
    Field(
        max_length=MAX_NAMES,
        description="Layer name or path -> the frames it may have pixels in, "
        'e.g. {"Sword": "3-5"}; a group covers all its layers',
    ),
]


def _check_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    findings = result["findings"]
    return {
        "ok": not any(f["severity"] == "error" for f in findings),
        "frames_checked": result["frames_checked"],
        "finding_count": result["finding_count"],
        "truncated": result["finding_count"] > len(findings),
        "findings": findings,
    }


@op_tool("check_animation", mutates=False, finish=_check_result)
def check_animation(
    frames: FrameSpec = "all",
    required_layers: LayerList = None,
    layer_frame_ranges: FrameRanges = None,
    overlap_pairs: Annotated[
        list[tuple[LayerRef, LayerRef]] | None,
        Field(max_length=MAX_NAMES, description="Layer pairs whose pixels must not overlap"),
    ] = None,
) -> dict[str, Any]:
    """Audit the animation without changing it; every layer is checked, nested ones too.

    Each finding is {kind, severity, message} plus layer and frame where they apply.
    Errors: missing_layer (a named layer does not exist), out_of_range (a layer has
    pixels in a frame outside its layer_frame_ranges entry), overlap (an overlap_pairs
    pair has pixels on the same canvas spot; with pixels and bounds).
    Warnings: missing_in_range (no pixels in a frame inside its range), ambiguous_layer
    (a bare name matches several layers; the shallowest is used), empty_frame (no
    visible pixels), cel_off_canvas, frame_duration (under 10 ms or over 10 s).
    Ranges and overlaps look at a layer's own pixels, hidden or not; tilemap layers are
    left out of overlap checks. The overlap scan covers where the pairs' cels meet, summed
    over pairs and frames; past ASEPRITE_MCP_MAX_SCAN_PIXELS (default 16777216) the call
    fails before scanning, so check fewer frames or pairs. ok is true when there is no
    error. At most 200 findings are listed (truncated says so; finding_count is the
    total). Only `frames` are checked.
    """
    return {
        "frames": frames,
        "required_layers": required_layers or [],
        "layer_frame_ranges": layer_frame_ranges or {},
        "overlap_pairs": [list(pair) for pair in overlap_pairs or []],
        "max_findings": MAX_FINDINGS,
        "max_scan_pixels": server.get_settings().max_scan_pixels,
    }


def _repair_result(result: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return {**result, "order": result.get("order")}


@op_tool("repair_animation", mutates=True, finish=_repair_result)
def repair_animation(
    frames: FrameSpec = "all",
    ensure_layers: Annotated[
        list[LayerRef] | None,
        Field(
            max_length=MAX_NAMES,
            description="Layers to create when missing; 'group/name' creates it in that group",
        ),
    ] = None,
    layer_order: Annotated[
        list[LayerRef] | None,
        Field(
            max_length=MAX_NAMES,
            description="Sibling layers in the wanted order, bottom first",
        ),
    ] = None,
    layer_frame_ranges: FrameRanges = None,
    out_of_range: Literal["report", "hide", "delete"] = "report",
) -> dict[str, Any]:
    """Fix the structure of an animation; everything is checked before anything changes.

    ensure_layers adds missing layers as empty image layers on top of their parent.
    layer_order puts the listed layers (all in the same group, or all top level) in that
    order, bottom first, in the stack slots they already hold; unlisted layers stay put.
    layer_frame_ranges finds layers with pixels in frames (within `frames`) outside their
    range (it may name a layer ensure_layers creates, by path or bare name);
    out_of_range decides what happens to them: "report" only lists them and
    changes nothing, "hide" makes each such layer invisible (its cels stay), "delete"
    deletes the out-of-range cels. Locked layers are refused for hide, delete and moves.
    changed is false when nothing needed fixing; the file is then not rewritten. When
    any step fails, nothing is saved.
    """
    order = layer_order
    if order is not None:
        if len(order) < 2:
            raise ValueError("layer_order needs at least two layers")
        if len(set(order)) != len(order):
            raise ValueError("layer_order names a layer twice")
    return {
        "frames": frames,
        "ensure_layers": ensure_layers or [],
        "layer_order": order,
        "layer_frame_ranges": layer_frame_ranges or {},
        "out_of_range": out_of_range,
    }


@op_tool("copy_layers", mutates=True, path_arg="target", reads="source")
def copy_layers(
    source: Annotated[str, Field(description="Sprite file to copy from; it is not changed")],
    layers: Annotated[
        list[LayerRef],
        Field(min_length=1, max_length=MAX_NAMES, description="Source layers or groups"),
    ],
    replace: Annotated[
        bool, Field(description="Replace a top-level target layer with the same name")
    ] = False,
    create_missing_frames: Annotated[
        bool,
        Field(description="Append frames the target lacks (with the source durations)"),
    ] = True,
) -> dict[str, Any]:
    """Copy layers from another sprite into the target, on top of its top level.

    A group comes with all its layers, nested groups included. Cels keep their frame
    number, position, opacity and z-index; linked cels stay linked. Layer name,
    visibility, opacity, blend mode, colour and user data are copied. Both sprites must
    have the same colour mode (indexed copies palette indices as they are, so give both
    the same palette). A name already used at the target's top level is an error unless
    replace is true, which puts the copy in the old layer's place. Without
    create_missing_frames, cels past the target's last frame are skipped and counted.
    Tilemap layers cannot be copied. Source and target must be different files.
    """
    return {
        "source": source,
        "layers": layers,
        "replace": replace,
        "create_missing_frames": create_missing_frames,
    }
