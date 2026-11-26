from typing import Annotated, Any, Literal

from pydantic import Field

from ._registry import op_tool

LayerRef = Annotated[
    str,
    Field(min_length=1, description="Layer name, or a 'group/child' path for nested layers"),
]
LayerName = Annotated[str, Field(min_length=1, description="Layer name")]
NewName = Annotated[str | None, Field(min_length=1, description="New layer name")]
BlendMode = Literal[
    "normal",
    "multiply",
    "screen",
    "overlay",
    "darken",
    "lighten",
    "color_dodge",
    "color_burn",
    "hard_light",
    "soft_light",
    "difference",
    "exclusion",
    "hue",
    "saturation",
    "color",
    "luminosity",
    "addition",
    "subtract",
    "divide",
]


@op_tool("add_layer", mutates=True)
def add_layer(
    name: LayerName,
    kind: Annotated[
        Literal["normal", "group", "tilemap"], Field(description="What to add")
    ] = "normal",
    parent: Annotated[
        str, Field(description="Group to add the layer to; empty for the top level")
    ] = "",
    tile_size: Annotated[
        int | None, Field(ge=1, le=256, description="Tile width and height, tilemap only")
    ] = None,
) -> dict[str, Any]:
    """Add a layer, group or tilemap layer on top of its parent's stack.

    Returns the new layer's path. Names do not have to be unique.
    """
    if kind == "tilemap" and tile_size is None:
        raise ValueError("a tilemap layer needs tile_size")
    if kind != "tilemap" and tile_size is not None:
        raise ValueError("tile_size only applies to tilemap layers")
    return {"name": name, "kind": kind, "parent": parent, "tile_size": tile_size}


@op_tool("update_layer", mutates=True)
def update_layer(
    layer: LayerRef,
    new_name: NewName = None,
    visible: Annotated[bool | None, Field(description="Show or hide the layer")] = None,
    locked: Annotated[
        bool | None, Field(description="Lock or unlock the layer against pixel and cel edits")
    ] = None,
    opacity: Annotated[int | None, Field(ge=0, le=255, description="Layer opacity, 0..255")] = None,
    blend_mode: Annotated[BlendMode | None, Field(description="Layer blend mode")] = None,
    parent: Annotated[
        str | None,
        Field(description="Group to move the layer into; empty string for the top level"),
    ] = None,
    stack_index: Annotated[
        int | None,
        Field(ge=1, description="Position inside the (new) parent, 1 = bottom"),
    ] = None,
) -> dict[str, Any]:
    """Rename, show/hide, lock/unlock, restyle or move a layer; only the given fields change.

    The layer is moved first (parent, then stack_index), then its properties are set.
    All of this works on locked layers too. Groups have no opacity or blend mode.
    Returns the layer's new path and stack index.
    """
    changes = {
        "new_name": new_name,
        "visible": visible,
        "locked": locked,
        "opacity": opacity,
        "blend_mode": blend_mode,
        "parent": parent,
        "stack_index": stack_index,
    }
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes:
        raise ValueError("nothing to change: pass at least one field besides layer")
    return {"layer": layer, **changes}


@op_tool("delete_layer", mutates=True)
def delete_layer(layer: LayerRef) -> dict[str, Any]:
    """Delete a layer; deleting a group deletes everything in it.

    The sprite must keep at least one layer. A locked layer, a layer in a locked group
    and a group holding a locked layer are refused.
    """
    return {"layer": layer}


@op_tool("duplicate_layer", mutates=True)
def duplicate_layer(layer: LayerRef, new_name: NewName = None) -> dict[str, Any]:
    """Copy a layer (a group with all its children) right above the original.

    The copy is named new_name, or "<name> copy". Returns the copy's path.
    """
    return {"layer": layer, "new_name": new_name}


@op_tool("merge_layer_down", mutates=True)
def merge_layer_down(layer: LayerRef) -> dict[str, Any]:
    """Merge a layer into the one below it in the same group, in every frame.

    Both must be image layers (not groups or tilemaps) and neither may be locked. The
    layer is merged even when hidden. Both layers' opacity is baked into the pixels and
    the merged layer is reset to opacity 255 and normal blend. Returns its path.
    """
    return {"layer": layer}


@op_tool("flatten_sprite", mutates=True)
def flatten_sprite() -> dict[str, Any]:
    """Flatten all visible layers into a single layer; hidden layers are dropped.

    Like every whole-sprite change, it ignores layer locks.
    """
    return {}
