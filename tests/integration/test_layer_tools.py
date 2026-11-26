from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.errors import ToolError

RED = [255, 0, 0, 255]
BLUE = [0, 0, 255, 255]
CLEAR = [0, 0, 0, 0]


def tree(info: dict) -> list:
    """Layer names bottom-to-top, groups as (name, [children])."""

    def walk(layers: list[dict]) -> list:
        return [
            (la["name"], walk(la["children"])) if la["type"] == "group" else la["name"]
            for la in layers
        ]

    return walk(info["layers"])


async def layer_tree(call, path: str = "a.aseprite") -> list:
    return tree(await call("get_sprite_info", path=path))


async def setup(call, *entries: dict) -> None:
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await call("batch", path="a.aseprite", ops=list(entries))


def add(name: str, **args) -> dict:
    return {"tool": "add_layer", "args": {"name": name, **args}}


async def test_add_layer_on_top(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    result = await call("add_layer", path="a.aseprite", name="Ink")

    assert result["layer"] == "Ink"
    assert await layer_tree(call) == ["Layer 1", "Ink"]


async def test_add_layer_inside_group(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"))

    result = await call("add_layer", path="a.aseprite", name="B", parent="G")

    assert result["layer"] == "G/B"
    assert await layer_tree(call) == ["Layer 1", ("G", ["A", "B"])]


async def test_add_layer_unknown_parent_fails(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="parent group 'Nope' not found"):
        await call("add_layer", path="a.aseprite", name="B", parent="Nope")


async def test_add_layer_parent_must_be_a_group(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="'Layer 1' is not a group"):
        await call("add_layer", path="a.aseprite", name="B", parent="Layer 1")


async def test_add_group_and_nested_info(call):
    await setup(call, add("Body", kind="group"), add("Arms", kind="group", parent="Body"))

    await call("add_layer", path="a.aseprite", name="Left", parent="Body/Arms")

    info = await call("get_sprite_info", path="a.aseprite")
    body = info["layers"][1]
    assert (body["path"], body["type"]) == ("Body", "group")
    arms = body["children"][0]
    assert (arms["path"], arms["type"]) == ("Body/Arms", "group")
    assert arms["children"][0]["path"] == "Body/Arms/Left"


async def test_add_tilemap_layer_reports_type(call):
    await call("create_sprite", path="a.aseprite", width=16, height=16)

    result = await call("add_layer", path="a.aseprite", name="Floor", kind="tilemap", tile_size=8)

    assert result == {"layer": "Floor", "type": "tilemap"}
    info = await call("get_sprite_info", path="a.aseprite")
    assert [(la["name"], la["type"]) for la in info["layers"]] == [
        ("Layer 1", "normal"),
        ("Floor", "tilemap"),
    ]


async def test_add_tilemap_needs_tile_size(call):
    await call("create_sprite", path="a.aseprite", width=16, height=16)

    with pytest.raises(ToolError, match="tile_size"):
        await call("add_layer", path="a.aseprite", name="Floor", kind="tilemap")


async def test_add_normal_layer_rejects_tile_size(call):
    await call("create_sprite", path="a.aseprite", width=16, height=16)

    with pytest.raises(ToolError, match="tile_size"):
        await call("add_layer", path="a.aseprite", name="Ink", tile_size=8)


async def test_update_layer_renames_and_sets_opacity(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    result = await call(
        "update_layer",
        path="a.aseprite",
        layer="Layer 1",
        new_name="Sketch",
        opacity=80,
        visible=False,
        blend_mode="multiply",
    )

    assert result["layer"] == "Sketch"
    [layer] = (await call("get_sprite_info", path="a.aseprite"))["layers"]
    assert (layer["name"], layer["opacity"], layer["visible"], layer["blend_mode"]) == (
        "Sketch",
        80,
        False,
        "multiply",
    )


async def test_update_layer_nested_stack_index(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"), add("B", parent="G"))

    result = await call("update_layer", path="a.aseprite", layer="G/B", stack_index=1)

    assert result == {"layer": "G/B", "stack_index": 1}
    assert await layer_tree(call) == ["Layer 1", ("G", ["B", "A"])]


async def test_update_layer_stack_index_out_of_range_fails(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"), add("B", parent="G"))
    await call("add_layer", path="a.aseprite", name="Top")

    with pytest.raises(ToolError, match="stack_index 3 is out of range: 'G' holds 2 layers"):
        await call("update_layer", path="a.aseprite", layer="A", stack_index=3)


async def test_update_layer_moves_into_group_at_stack_index(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"), add("B", parent="G"))

    await call("update_layer", path="a.aseprite", layer="Layer 1", parent="G", stack_index=2)

    assert await layer_tree(call) == [("G", ["A", "Layer 1", "B"])]


async def test_update_layer_moves_out_to_top_level(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"))

    await call("update_layer", path="a.aseprite", layer="G/A", parent="")

    assert await layer_tree(call) == ["Layer 1", ("G", []), "A"]


async def test_update_layer_move_group_into_itself_fails(call):
    await setup(call, add("G", kind="group"), add("H", kind="group", parent="G"))

    with pytest.raises(ToolError, match="cannot move 'G' into itself"):
        await call("update_layer", path="a.aseprite", layer="G", parent="G/H")

    assert await layer_tree(call) == ["Layer 1", ("G", [("H", [])])]


async def test_update_layer_no_changes_fails(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="nothing to change"):
        await call("update_layer", path="a.aseprite", layer="Layer 1")


async def test_update_group_opacity_is_refused(call):
    await setup(call, add("G", kind="group"))

    with pytest.raises(ToolError, match="group 'G' has no opacity or blend mode"):
        await call("update_layer", path="a.aseprite", layer="G", opacity=10)


async def test_update_unknown_layer_names_it(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="layer 'Ghost' not found"):
        await call("update_layer", path="a.aseprite", layer="Ghost", visible=False)


async def test_delete_layer(call):
    await setup(call, add("Ink"))

    result = await call("delete_layer", path="a.aseprite", layer="Layer 1")

    assert result == {"deleted": "Layer 1", "layers_left": 1}
    assert await layer_tree(call) == ["Ink"]


async def test_delete_last_layer_refused(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"))
    await call("delete_layer", path="a.aseprite", layer="Layer 1")

    await call("delete_layer", path="a.aseprite", layer="G/A")
    with pytest.raises(ToolError, match="cannot delete 'G': the sprite needs at least one layer"):
        await call("delete_layer", path="a.aseprite", layer="G")

    assert await layer_tree(call) == [("G", [])]


async def test_delete_group_removes_children(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"), add("B", parent="G"))

    result = await call("delete_layer", path="a.aseprite", layer="G")

    assert result == {"deleted": "G", "layers_left": 1}
    assert await layer_tree(call) == ["Layer 1"]


async def test_duplicate_layer_keeps_pixels_and_position(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await pixels(path, put=[(5, 6, *RED)])
    await call("update_layer", path="a.aseprite", layer="Layer 1", opacity=120)

    result = await call("duplicate_layer", path="a.aseprite", layer="Layer 1")

    assert result == {"layer": "Layer 1 copy", "stack_index": 2}
    assert await pixels(path, read=[(5, 6), (0, 0)], layer="Layer 1 copy") == [RED, CLEAR]
    copy = (await call("get_sprite_info", path="a.aseprite"))["layers"][1]
    assert copy["opacity"] == 120


async def test_duplicate_layer_sits_right_above_source(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"), add("B", parent="G"))

    result = await call("duplicate_layer", path="a.aseprite", layer="G/A", new_name="A2")

    assert result == {"layer": "G/A2", "stack_index": 2}
    assert await layer_tree(call) == ["Layer 1", ("G", ["A", "A2", "B"])]


async def test_duplicate_group_copies_children(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await setup(call, add("G", kind="group"), add("A", parent="G"), add("B", parent="G"))
    await pixels(path, put=[(1, 2, *RED)], layer="G/A")
    await pixels(path, put=[(3, 4, *BLUE)], layer="G/B")

    result = await call("duplicate_layer", path="a.aseprite", layer="G", new_name="G2")

    assert result["layer"] == "G2"
    assert await layer_tree(call) == ["Layer 1", ("G", ["A", "B"]), ("G2", ["A", "B"])]
    assert await pixels(path, read=[(1, 2)], layer="G2/A") == [RED]
    assert await pixels(path, read=[(3, 4)], layer="G2/B") == [BLUE]


async def test_merge_layer_down_combines_pixels(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await setup(call, add("Top"))
    await pixels(path, put=[(0, 0, *RED)])
    await pixels(path, put=[(1, 1, *BLUE)], layer="Top")

    result = await call("merge_layer_down", path="a.aseprite", layer="Top")

    assert result == {"layer": "Layer 1"}
    assert await layer_tree(call) == ["Layer 1"]
    assert await pixels(path, read=[(0, 0), (1, 1)]) == [RED, BLUE]


async def test_merge_into_group_refused(call):
    await setup(call, add("G", kind="group"), add("Top"))

    with pytest.raises(ToolError, match="the layer below 'Top' is the group 'G'"):
        await call("merge_layer_down", path="a.aseprite", layer="Top")


async def test_merge_bottom_layer_refused(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"))

    with pytest.raises(ToolError, match="'G/A' has no layer below it"):
        await call("merge_layer_down", path="a.aseprite", layer="G/A")


async def test_flatten_sprite_drops_hidden_layers(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await setup(call, add("G", kind="group"), add("Hidden", parent="G"), add("Shown", parent="G"))
    await pixels(path, put=[(0, 0, *RED)])
    await pixels(path, put=[(0, 0, *BLUE), (2, 2, *BLUE)], layer="G/Hidden")
    await pixels(path, put=[(3, 3, *BLUE)], layer="G/Shown")
    await call("update_layer", path="a.aseprite", layer="G/Hidden", visible=False)

    result = await call("flatten_sprite", path="a.aseprite")

    assert result == {"layer": "Flattened", "dropped_hidden": ["G/Hidden"]}
    assert await layer_tree(call) == ["Flattened"]
    assert await pixels(path, read=[(0, 0), (2, 2), (3, 3)]) == [RED, CLEAR, BLUE]


async def test_layer_name_with_quotes_and_slash(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    await call("add_layer", path="a.aseprite", name='a"b')
    await call("add_layer", path="a.aseprite", name="x/y")
    renamed = await call("update_layer", path="a.aseprite", layer='a"b', new_name="it's")
    hidden = await call("update_layer", path="a.aseprite", layer="x/y", visible=False)

    assert (renamed["layer"], hidden["layer"]) == ("it's", "x/y")
    assert await layer_tree(call) == ["Layer 1", "it's", "x/y"]


async def test_layer_tools_work_in_batch(call, monkeypatch: pytest.MonkeyPatch):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    calls = []
    real_run_script = ops.run_script

    async def counting_run_script(*args, **kwargs):
        calls.append(args[0])
        return await real_run_script(*args, **kwargs)

    monkeypatch.setattr(ops, "run_script", counting_run_script)

    result = await call(
        "batch",
        path="a.aseprite",
        ops=[
            {"tool": "add_layer", "args": {"name": "Ink"}},
            {"tool": "update_layer", "args": {"layer": "Ink", "new_name": "Lines", "opacity": 5}},
        ],
    )

    assert len(calls) == 1
    assert [r["layer"] for r in result["result"]] == ["Ink", "Lines"]
    assert await layer_tree(call) == ["Layer 1", "Lines"]


async def test_flatten_sprite_without_hidden_layers(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"))

    result = await call("flatten_sprite", path="a.aseprite")

    assert result == {"layer": "Flattened", "dropped_hidden": []}


async def test_flatten_with_everything_hidden_fails(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await call("update_layer", path="a.aseprite", layer="Layer 1", visible=False)

    with pytest.raises(ToolError, match="no visible layer"):
        await call("flatten_sprite", path="a.aseprite")


async def test_failed_batch_rolls_back_layer_changes(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match=r"op 3 \(delete_layer\): layer 'Ghost' not found"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                add("G", kind="group"),
                {"tool": "duplicate_layer", "args": {"layer": "Layer 1"}},
                {"tool": "delete_layer", "args": {"layer": "Ghost"}},
            ],
        )

    assert await layer_tree(call) == ["Layer 1"]


async def test_update_layer_locks_and_unlocks(call, locks, tmp_path: Path):
    await setup(call, add("Ink"))

    await call("update_layer", path="a.aseprite", layer="Ink", locked=True)
    assert await locks(tmp_path / "a.aseprite") == ["Ink"]

    await call("update_layer", path="a.aseprite", layer="Ink", locked=False)
    assert await locks(tmp_path / "a.aseprite") == []


async def test_sprite_info_reports_locked_layers(call, locks, tmp_path: Path):
    await setup(call, add("G", kind="group"), add("A", parent="G"))
    await locks(tmp_path / "a.aseprite", lock=["G"])

    info = await call("get_sprite_info", path="a.aseprite")

    layer, group = info["layers"]
    assert (layer["locked"], group["locked"], group["children"][0]["locked"]) == (
        False,
        True,
        False,
    )


async def test_locked_layer_can_be_renamed_and_hidden(call, locks, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])

    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name="Ink", visible=False)

    [layer] = (await call("get_sprite_info", path="a.aseprite"))["layers"]
    assert (layer["name"], layer["visible"], layer["locked"]) == ("Ink", False, True)


async def test_delete_layer_refuses_locked_layer(call, locks, tmp_path: Path):
    await setup(call, add("Ink"))
    await locks(tmp_path / "a.aseprite", lock=["Ink"])

    with pytest.raises(ToolError, match="'Ink' is locked; unlock it first"):
        await call("delete_layer", path="a.aseprite", layer="Ink")

    assert await layer_tree(call) == ["Layer 1", "Ink"]


async def test_delete_group_refuses_locked_child(call, locks, tmp_path: Path):
    await setup(call, add("G", kind="group"), add("A", parent="G"))
    await locks(tmp_path / "a.aseprite", lock=["G/A"])

    with pytest.raises(ToolError, match="'G/A' is locked"):
        await call("delete_layer", path="a.aseprite", layer="G")

    assert await layer_tree(call) == ["Layer 1", ("G", ["A"])]


async def test_delete_layer_refuses_layer_in_locked_group(call, locks, tmp_path: Path):
    await setup(call, add("G", kind="group"), add("A", parent="G"))
    await locks(tmp_path / "a.aseprite", lock=["G"])

    with pytest.raises(ToolError, match="'G/A' is inside the locked group 'G'"):
        await call("delete_layer", path="a.aseprite", layer="G/A")


async def test_merge_layer_down_refuses_locked_layer(call, locks, tmp_path: Path):
    await setup(call, add("Ink"))
    await locks(tmp_path / "a.aseprite", lock=["Ink"])

    with pytest.raises(ToolError, match="'Ink' is locked"):
        await call("merge_layer_down", path="a.aseprite", layer="Ink")

    assert await layer_tree(call) == ["Layer 1", "Ink"]


async def test_merge_layer_down_refuses_locked_layer_below(call, locks, tmp_path: Path):
    await setup(call, add("Ink"))
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call("merge_layer_down", path="a.aseprite", layer="Ink")

    assert await layer_tree(call) == ["Layer 1", "Ink"]


async def test_flatten_sprite_ignores_locks(call, locks, tmp_path: Path):
    await setup(call, add("Ink"))
    await locks(tmp_path / "a.aseprite", lock=["Ink"])

    await call("flatten_sprite", path="a.aseprite")

    assert len(await layer_tree(call)) == 1


async def test_update_layer_stack_index_error_says_1_layer_in_singular(call):
    await setup(call, add("G", kind="group"), add("A", parent="G"))

    with pytest.raises(ToolError, match="'G' holds 1 layer$"):
        await call("update_layer", path="a.aseprite", layer="G/A", stack_index=2)


async def test_background_layer_cannot_move_into_a_group(call, pixels, tmp_path: Path):
    await setup(call, add("G", kind="group"))
    await pixels(tmp_path / "a.aseprite", background=True)

    with pytest.raises(ToolError, match="'Background' is the background layer and cannot be moved"):
        await call("update_layer", path="a.aseprite", layer="Background", parent="G")


async def test_background_layer_cannot_change_stack_index(call, pixels, tmp_path: Path):
    await setup(call, add("Ink"))
    await pixels(tmp_path / "a.aseprite", background=True)

    with pytest.raises(ToolError, match="'Background' is the background layer and cannot be moved"):
        await call("update_layer", path="a.aseprite", layer="Background", stack_index=2)

    assert await layer_tree(call) == ["Background", "Ink"]


async def test_background_layer_opacity_is_refused(call, pixels, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await pixels(tmp_path / "a.aseprite", background=True)

    with pytest.raises(ToolError, match="its opacity and blend mode are fixed"):
        await call("update_layer", path="a.aseprite", layer="Background", opacity=100)


async def test_no_other_layer_can_take_stack_index_1_below_the_background(
    call, pixels, tmp_path: Path
):
    await setup(call, add("Ink"))
    await pixels(tmp_path / "a.aseprite", background=True)

    with pytest.raises(ToolError, match="stack_index 1 at the top level belongs to the background"):
        await call("update_layer", path="a.aseprite", layer="Ink", stack_index=1)

    assert await layer_tree(call) == ["Background", "Ink"]


async def test_duplicate_layer_keeps_blend_mode_and_visibility(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await call(
        "update_layer", path="a.aseprite", layer="Layer 1", blend_mode="multiply", visible=False
    )

    await call("duplicate_layer", path="a.aseprite", layer="Layer 1")

    copy = (await call("get_sprite_info", path="a.aseprite"))["layers"][1]
    assert (copy["name"], copy["blend_mode"], copy["visible"]) == (
        "Layer 1 copy",
        "multiply",
        False,
    )


async def test_duplicate_layer_on_indexed_sprite_keeps_indices(
    call, pixels, set_palette, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (0, 0, 255, 255)])
    await pixels(path, put=[(1, 1, *BLUE)])

    await call("duplicate_layer", path="a.aseprite", layer="Layer 1")

    read = [(1, 1), (0, 0)]
    assert await pixels(path, read=read, layer="Layer 1 copy", values=True) == [2, 0]


async def test_merge_layer_down_on_indexed_sprite_combines_indices(
    call, pixels, set_palette, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4, color_mode="indexed")
    await call("add_layer", path="a.aseprite", name="Top")
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (0, 0, 255, 255)])
    await pixels(path, put=[(0, 0, *RED)])
    await pixels(path, put=[(1, 1, *BLUE)], layer="Top")

    await call("merge_layer_down", path="a.aseprite", layer="Top")

    assert await pixels(path, read=[(0, 0), (1, 1), (0, 1)], values=True) == [1, 2, 0]


async def test_duplicate_layer_on_gray_sprite_keeps_pixels(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4, color_mode="grayscale")
    await pixels(path, put=[(1, 1, 90, 90, 90, 255)])

    await call("duplicate_layer", path="a.aseprite", layer="Layer 1")

    assert await pixels(path, read=[(1, 1)], layer="Layer 1 copy") == [[90, 90, 90, 255]]


async def test_merge_layer_down_on_gray_sprite_combines_pixels(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4, color_mode="grayscale")
    await call("add_layer", path="a.aseprite", name="Top")
    await pixels(path, put=[(0, 0, 40, 40, 40, 255)])
    await pixels(path, put=[(1, 1, 200, 200, 200, 255)], layer="Top")

    await call("merge_layer_down", path="a.aseprite", layer="Top")

    assert await pixels(path, read=[(0, 0), (1, 1)]) == [[40, 40, 40, 255], [200, 200, 200, 255]]


async def test_flatten_sprite_keeps_every_frame(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await setup(call, add("Top"))
    await call("add_frames", path="a.aseprite", count=1)
    await pixels(path, put=[(0, 0, *RED)], frame=1)
    await pixels(path, put=[(1, 1, *BLUE)], layer="Top", frame=2)

    await call("flatten_sprite", path="a.aseprite")

    info = await call("get_sprite_info", path="a.aseprite")
    assert len(info["frames"]) == 2
    assert await pixels(path, read=[(0, 0), (1, 1)], frame=1) == [RED, CLEAR]
    assert await pixels(path, read=[(0, 0), (1, 1)], frame=2) == [CLEAR, BLUE]
