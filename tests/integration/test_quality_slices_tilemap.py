import dataclasses
import json
from pathlib import Path

import pytest

from aseprite_mcp import server
from aseprite_mcp.errors import ToolError
from helpers import rect

RED = "#ff0000"
BLUE = "#0000ff"


def op(tool: str, **args) -> dict:
    return {"tool": tool, "args": args}


def dot(x: int, y: int, layer: str, frame: int = 1, color: str = RED) -> dict:
    return op("draw_pixels", pixels=[{"x": x, "y": y, "color": color}], layer=layer, frame=frame)


async def setup(call, *entries: dict, name: str = "a.aseprite", **args) -> None:
    await call("create_sprite", path=name, width=8, height=8, **args)
    if entries:
        await call("batch", path=name, ops=list(entries))


def kinds(result: dict) -> list[tuple]:
    return [(f["kind"], f.get("layer"), f.get("frame")) for f in result["findings"]]


async def layer_names(call, path: str = "a.aseprite") -> list[str]:
    info = await call("get_sprite_info", path=path)
    return [layer["name"] for layer in info["layers"]]


# check_animation


async def test_audit_finds_nested_layer(call):
    await setup(
        call,
        op("add_frames"),
        op("add_layer", name="Body", kind="group"),
        op("add_layer", name="Arm", parent="Body"),
        dot(1, 1, "Body/Arm", frame=1),
        dot(1, 1, "Body/Arm", frame=2),
    )

    result = await call(
        "check_animation",
        path="a.aseprite",
        required_layers=["Arm"],
        layer_frame_ranges={"Arm": "1"},
    )

    assert kinds(result) == [("out_of_range", "Body/Arm", 2)]
    assert result["ok"] is False


async def test_check_animation_reports_missing_required_layer(call):
    await setup(call, dot(0, 0, "Layer 1"))

    result = await call("check_animation", path="a.aseprite", required_layers=["Shadow"])

    assert kinds(result) == [("missing_layer", "Shadow", None)]
    assert result["findings"][0]["severity"] == "error"


async def test_check_animation_clean_sprite_is_ok(call):
    await setup(call, dot(0, 0, "Layer 1"))

    result = await call("check_animation", path="a.aseprite", required_layers=["Layer 1"])

    assert result["ok"] is True
    assert result["findings"] == []


async def test_check_animation_reports_overlap_pair(call):
    await setup(
        call,
        op("add_layer", name="Hat"),
        dot(2, 2, "Layer 1"),
        dot(3, 2, "Layer 1"),
        dot(3, 2, "Hat", color=BLUE),
        dot(5, 5, "Hat", color=BLUE),
    )

    result = await call("check_animation", path="a.aseprite", overlap_pairs=[["Layer 1", "Hat"]])

    [finding] = result["findings"]
    assert finding["kind"] == "overlap"
    assert finding["frame"] == 1
    assert finding["pixels"] == 1
    assert finding["bounds"] == rect(3, 2, 1, 1)


async def test_check_animation_overlap_on_indexed_sprite(call):
    await setup(
        call,
        op("add_layer", name="Hat"),
        dot(1, 1, "Layer 1"),
        dot(1, 1, "Hat", color=BLUE),
        color_mode="indexed",
    )

    result = await call("check_animation", path="a.aseprite", overlap_pairs=[["Layer 1", "Hat"]])

    assert [(f["kind"], f["pixels"]) for f in result["findings"]] == [("overlap", 1)]


def box(x: int, y: int, w: int, h: int, layer: str, color: str = RED) -> dict:
    return op("draw_rect", rect=rect(x, y, w, h), color=color, fill=True, layer=layer)


async def test_check_animation_counts_overlap_of_partly_covering_layers(call):
    await setup(
        call,
        op("add_layer", name="Hat"),
        box(0, 0, 4, 3, "Layer 1"),
        box(2, 1, 5, 5, "Hat", color="#0000ff40"),
        dot(7, 7, "Layer 1"),
    )

    result = await call("check_animation", path="a.aseprite", overlap_pairs=[["Layer 1", "Hat"]])

    [finding] = result["findings"]
    assert finding["pixels"] == 4
    assert finding["bounds"] == rect(2, 1, 2, 2)


async def test_check_animation_overlap_with_indexed_background(call, pixels, tmp_path: Path):
    await setup(call, op("add_frames"), color_mode="indexed")
    await pixels(tmp_path / "a.aseprite", background=True)
    await call("batch", path="a.aseprite", ops=[op("add_layer", name="Hat"), dot(2, 2, "Hat")])

    result = await call(
        "check_animation", path="a.aseprite", frames="1", overlap_pairs=[["Background", "Hat"]]
    )

    assert [(f["kind"], f["pixels"]) for f in result["findings"]] == [("overlap", 1)]


async def test_check_animation_refuses_overlap_scan_over_limit(
    call, ase_settings, monkeypatch: pytest.MonkeyPatch
):
    await setup(
        call, op("add_layer", name="Hat"), box(0, 0, 4, 4, "Layer 1"), box(2, 2, 4, 4, "Hat")
    )
    small = dataclasses.replace(ase_settings, max_scan_pixels=15)
    monkeypatch.setattr(server, "get_settings", lambda: small)

    with pytest.raises(ToolError, match="would scan 16 pixels .* more than the limit of 15"):
        await call("check_animation", path="a.aseprite", overlap_pairs=[["Layer 1", "Hat"]])


async def test_check_animation_warns_about_ambiguous_name(call):
    await setup(
        call,
        op("add_layer", name="G", kind="group"),
        op("add_layer", name="Layer 1", parent="G"),
        dot(0, 0, "Layer 1"),
    )

    result = await call("check_animation", path="a.aseprite", required_layers=["Layer 1"])

    assert kinds(result) == [("ambiguous_layer", "Layer 1", None)]
    assert result["ok"] is True


async def test_check_animation_reports_empty_frame_as_warning(call):
    await setup(call, op("add_frames"), dot(0, 0, "Layer 1"))

    result = await call("check_animation", path="a.aseprite")

    assert kinds(result) == [("empty_frame", None, 2)]
    assert result["ok"] is True


async def test_check_animation_reports_missing_cel_in_range(call):
    await setup(call, op("add_frames", count=2), dot(0, 0, "Layer 1"), dot(0, 0, "Layer 1", 3))

    result = await call(
        "check_animation", path="a.aseprite", frames="1-2", layer_frame_ranges={"Layer 1": "all"}
    )

    assert ("missing_in_range", "Layer 1", 2) in kinds(result)
    assert all(f["frame"] != 3 for f in result["findings"])


async def test_check_animation_truncates_findings(call):
    await setup(call, dot(0, 0, "Layer 1"))

    result = await call(
        "check_animation", path="a.aseprite", required_layers=[f"L{i}" for i in range(205)]
    )

    assert len(result["findings"]) == 200
    assert result["finding_count"] == 205
    assert result["truncated"] is True


async def test_read_only_tools_keep_file_bytes(call, tmp_path: Path):
    await setup(
        call,
        op("add_layer", name="Floor", kind="tilemap", tile_size=4),
        op("create_slice", name="Button", rect=rect(0, 0, 4, 4)),
        dot(1, 1, "Layer 1"),
    )
    before = (tmp_path / "a.aseprite").read_bytes()

    await call("check_animation", path="a.aseprite", required_layers=["Nope"])
    await call("list_slices", path="a.aseprite")
    await call("get_tilemap_info", path="a.aseprite", layer="Floor")

    assert (tmp_path / "a.aseprite").read_bytes() == before


# repair_animation


async def test_repair_animation_default_is_report_only(call, tmp_path: Path):
    await setup(call, op("add_frames"), dot(0, 0, "Layer 1"), dot(0, 0, "Layer 1", frame=2))
    before = (tmp_path / "a.aseprite").stat()

    result = await call("repair_animation", path="a.aseprite", layer_frame_ranges={"Layer 1": "1"})

    assert result["out_of_range"] == [{"layer": "Layer 1", "frames": [2]}]
    assert result["changed"] is False
    after = (tmp_path / "a.aseprite").stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


async def test_fix_invalid_range_errors(call):
    await setup(call, op("add_frames"))

    with pytest.raises(ToolError, match="runs backwards"):
        await call("repair_animation", path="a.aseprite", layer_frame_ranges={"Layer 1": "2-1"})


async def test_repair_range_past_last_frame_changes_nothing(call, tmp_path: Path):
    await setup(call, op("add_frames"))
    before = (tmp_path / "a.aseprite").read_bytes()

    with pytest.raises(
        ToolError, match=r"layer_frame_ranges\['Layer 1'\]: frame 3 is out of range"
    ):
        await call(
            "repair_animation",
            path="a.aseprite",
            ensure_layers=["Shadow"],
            layer_frame_ranges={"Layer 1": "1-5"},
            out_of_range="delete",
        )

    assert (tmp_path / "a.aseprite").read_bytes() == before


async def test_repair_ensure_layers_creates_missing(call):
    await setup(call)

    result = await call("repair_animation", path="a.aseprite", ensure_layers=["Layer 1", "Shadow"])

    assert result["created"] == ["Shadow"]
    assert result["changed"] is True
    assert await layer_names(call) == ["Layer 1", "Shadow"]


async def test_repair_ensure_layers_inside_group(call):
    await setup(call, op("add_layer", name="G", kind="group"))

    result = await call("repair_animation", path="a.aseprite", ensure_layers=["G/Shadow"])

    assert result["created"] == ["G/Shadow"]


async def test_repair_range_may_name_a_layer_it_creates(call):
    await setup(call, op("add_layer", name="G", kind="group"))

    result = await call(
        "repair_animation",
        path="a.aseprite",
        ensure_layers=["G/X"],
        layer_frame_ranges={"X": "1"},
    )

    assert result["created"] == ["G/X"]
    assert result["missing_in_range"] == [{"layer": "G/X", "frames": [1]}]


async def test_batch_saves_when_only_some_ops_change_nothing(call):
    await setup(call)
    report = op("repair_animation", layer_frame_ranges={"Layer 1": "1"})

    await call("batch", path="a.aseprite", ops=[dot(1, 1, "Layer 1"), report])
    await call("batch", path="a.aseprite", ops=[report, dot(2, 2, "Layer 1", color=BLUE)])

    read = await call("read_pixels", path="a.aseprite", rect=rect(1, 1, 2, 2), format="hex")
    assert read["rows"] == ["#ff0000 .", ". #0000ff"]


async def test_repair_layer_order_is_bottom_to_top(call):
    await setup(call, op("add_layer", name="B"), op("add_layer", name="C"))

    await call("repair_animation", path="a.aseprite", layer_order=["C", "Layer 1", "B"])

    assert await layer_names(call) == ["C", "Layer 1", "B"]


async def test_repair_layer_order_keeps_unlisted_layers_in_place(call):
    await setup(call, op("add_layer", name="B"), op("add_layer", name="C"))

    await call("repair_animation", path="a.aseprite", layer_order=["C", "Layer 1"])

    assert await layer_names(call) == ["C", "B", "Layer 1"]


async def test_repair_layer_order_unknown_layer_errors(call):
    await setup(call, op("add_layer", name="B"))

    with pytest.raises(ToolError, match="layer 'Ghost' not found"):
        await call("repair_animation", path="a.aseprite", layer_order=["B", "Ghost"])


async def test_repair_out_of_range_delete_removes_cels(call, cels, tmp_path: Path):
    await setup(call, op("add_frames", count=2), *(dot(0, 0, "Layer 1", f) for f in (1, 2, 3)))

    result = await call(
        "repair_animation",
        path="a.aseprite",
        layer_frame_ranges={"Layer 1": "1-2"},
        out_of_range="delete",
    )

    assert result["deleted_cels"] == 1
    assert [bool(c) for c in await cels(tmp_path / "a.aseprite")] == [True, True, False]


async def test_repair_delete_keeps_linked_frame_in_range(call, cels, pixels, tmp_path: Path):
    await setup(
        call,
        op("add_frames", count=2),
        dot(0, 0, "Layer 1"),
        op("copy_frames", source=1, targets="2-3", link=True),
    )

    await call(
        "repair_animation",
        path="a.aseprite",
        layer_frame_ranges={"Layer 1": "1"},
        out_of_range="delete",
    )

    assert [bool(c) for c in await cels(tmp_path / "a.aseprite")] == [True, False, False]
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0)]) == [[255, 0, 0, 255]]


async def test_repair_refuses_deleting_background_cels(call, pixels, tmp_path: Path):
    await setup(call, op("add_frames"))
    await pixels(tmp_path / "a.aseprite", background=True)

    with pytest.raises(ToolError, match="background layer; its cels cannot be deleted"):
        await call(
            "repair_animation",
            path="a.aseprite",
            layer_frame_ranges={"Background": "1"},
            out_of_range="delete",
        )


async def test_repair_out_of_range_hide_hides_layer(call):
    await setup(call, op("add_frames"), op("add_layer", name="Fx"), dot(0, 0, "Fx", frame=2))

    result = await call(
        "repair_animation",
        path="a.aseprite",
        layer_frame_ranges={"Fx": "1", "Layer 1": "1"},
        out_of_range="hide",
    )

    assert result["hidden"] == ["Fx"]
    info = await call("get_sprite_info", path="a.aseprite")
    assert [la["visible"] for la in info["layers"]] == [True, False]


async def test_repair_refuses_locked_layer(call, locks, tmp_path: Path):
    await setup(call, op("add_frames"), dot(0, 0, "Layer 1", frame=2))
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call(
            "repair_animation",
            path="a.aseprite",
            layer_frame_ranges={"Layer 1": "1"},
            out_of_range="delete",
        )


# copy_layers


async def source_sprite(call, *entries: dict) -> None:
    await setup(
        call, op("update_layer", layer="Layer 1", new_name="Ink"), *entries, name="src.aseprite"
    )


async def test_copy_layers_keeps_opacity(call, pixels, tmp_path: Path):
    await source_sprite(
        call,
        dot(2, 3, "Ink"),
        op("update_layer", layer="Ink", opacity=100, blend_mode="multiply", visible=False),
    )
    await setup(call, name="dst.aseprite")

    result = await call("copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Ink"])

    assert result["layers"] == ["Ink"]
    info = await call("get_sprite_info", path="dst.aseprite")
    ink = info["layers"][1]
    assert (ink["name"], ink["opacity"], ink["blend_mode"], ink["visible"]) == (
        "Ink",
        100,
        "multiply",
        False,
    )
    assert await pixels(tmp_path / "dst.aseprite", read=[(2, 3)], layer="Ink") == [[255, 0, 0, 255]]


async def test_copy_layers_copies_group_children(call, pixels, tmp_path: Path):
    await source_sprite(
        call,
        op("add_layer", name="Body", kind="group"),
        op("add_layer", name="Arm", parent="Body"),
        op("add_layer", name="Hand", kind="group", parent="Body"),
        op("add_layer", name="Finger", parent="Body/Hand"),
        dot(1, 1, "Body/Hand/Finger"),
    )
    await setup(call, name="dst.aseprite")

    result = await call(
        "copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Body"]
    )

    assert result["layers"] == ["Body"]
    info = await call("get_sprite_info", path="dst.aseprite")
    body = info["layers"][1]
    assert [c["path"] for c in body["children"]] == ["Body/Arm", "Body/Hand"]
    assert body["children"][1]["children"][0]["path"] == "Body/Hand/Finger"
    finger = await pixels(tmp_path / "dst.aseprite", read=[(1, 1)], layer="Body/Hand/Finger")
    assert finger == [[255, 0, 0, 255]]


async def test_copy_layers_name_clash_needs_replace(call):
    await source_sprite(call)
    await setup(call, op("update_layer", layer="Layer 1", new_name="Ink"), name="dst.aseprite")

    with pytest.raises(ToolError, match="already has a layer 'Ink'; pass replace=true"):
        await call("copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Ink"])


async def test_copy_layers_replace_takes_the_old_layers_place(call, pixels, tmp_path: Path):
    await source_sprite(call, dot(0, 0, "Ink"))
    await setup(
        call,
        op("update_layer", layer="Layer 1", new_name="Ink"),
        op("add_layer", name="Top"),
        dot(5, 5, "Ink", color=BLUE),
        name="dst.aseprite",
    )

    result = await call(
        "copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Ink"], replace=True
    )

    assert result["replaced"] == ["Ink"]
    assert await layer_names(call, "dst.aseprite") == ["Ink", "Top"]
    assert await pixels(tmp_path / "dst.aseprite", read=[(0, 0), (5, 5)], layer="Ink") == [
        [255, 0, 0, 255],
        [0, 0, 0, 0],
    ]


async def test_copy_layers_creates_missing_frames(call):
    await source_sprite(call, op("add_frames", count=2, duration_ms=250), dot(0, 0, "Ink", frame=3))
    await setup(call, name="dst.aseprite")

    result = await call("copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Ink"])

    assert result["frames_added"] == 2
    info = await call("get_sprite_info", path="dst.aseprite")
    assert [f["duration_ms"] for f in info["frames"]] == [100, 250, 250]


async def test_copy_layers_can_skip_frames_the_target_lacks(call):
    await source_sprite(call, op("add_frames", count=2), dot(0, 0, "Ink", frame=3))
    await setup(call, name="dst.aseprite")

    result = await call(
        "copy_layers",
        source="src.aseprite",
        target="dst.aseprite",
        layers=["Ink"],
        create_missing_frames=False,
    )

    assert result["frames_added"] == 0
    assert result["skipped_cels"] == 1
    assert len((await call("get_sprite_info", path="dst.aseprite"))["frames"]) == 1


async def test_copy_layers_keeps_linked_cels(call, cels, tmp_path: Path):
    await source_sprite(
        call,
        op("add_frames", count=2),
        dot(0, 0, "Ink"),
        op("copy_frames", source=1, targets="2-3", link=True),
    )
    await setup(call, name="dst.aseprite")

    await call("copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Ink"])

    copied = await cels(tmp_path / "dst.aseprite", layer="Ink")
    assert len({c["image_id"] for c in copied}) == 1


async def test_copy_layers_refuses_color_mode_mismatch(call):
    await source_sprite(call)
    await setup(call, name="dst.aseprite", color_mode="indexed")

    with pytest.raises(ToolError, match="source is rgb but the target is indexed"):
        await call("copy_layers", source="src.aseprite", target="dst.aseprite", layers=["Ink"])


async def test_copy_layers_refuses_same_file(call):
    await source_sprite(call)

    with pytest.raises(ToolError, match="must be a different file"):
        await call("copy_layers", source="src.aseprite", target="src.aseprite", layers=["Ink"])


async def test_copy_layers_refuses_missing_target(call):
    await source_sprite(call)

    with pytest.raises(ToolError, match="File not found"):
        await call("copy_layers", source="src.aseprite", target="nope.aseprite", layers=["Ink"])


# slices


async def test_create_and_list_slice(call):
    await setup(call)

    await call(
        "create_slice",
        path="a.aseprite",
        name="Button",
        rect=rect(1, 1, 6, 5),
        center=rect(2, 2, 2, 1),
        pivot={"x": 3, "y": 4},
        color="#00ff00",
    )

    result = await call("list_slices", path="a.aseprite")
    assert result["slices"] == [
        {
            "name": "Button",
            "bounds": rect(1, 1, 6, 5),
            "center": rect(2, 2, 2, 1),
            "pivot": {"x": 3, "y": 4},
            "color": "#00ff00",
            "data": "",
        }
    ]


async def test_slice_names_with_quotes_valid_json(call):
    await setup(call)
    name = 'say "hi" \\ é'

    await call("create_slice", path="a.aseprite", name=name, rect=rect(0, 0, 2, 2))

    content, _ = await server.mcp.call_tool("list_slices", {"path": "a.aseprite"})
    assert json.loads(content[0].text)["slices"][0]["name"] == name


async def test_create_slice_duplicate_name_errors(call):
    await setup(call, op("create_slice", name="Button", rect=rect(0, 0, 2, 2)))

    with pytest.raises(ToolError, match="slice 'Button' already exists"):
        await call("create_slice", path="a.aseprite", name="Button", rect=rect(1, 1, 2, 2))


async def test_create_slice_center_must_fit(call):
    await setup(call)

    with pytest.raises(ToolError, match="center must lie inside the slice"):
        await call(
            "create_slice",
            path="a.aseprite",
            name="B",
            rect=rect(0, 0, 4, 4),
            center=rect(2, 2, 3, 1),
        )


async def test_update_slice_moves_it(call):
    await setup(call, op("create_slice", name="Button", rect=rect(0, 0, 2, 2)))

    result = await call(
        "update_slice",
        path="a.aseprite",
        name="Button",
        rect=rect(3, 3, 4, 4),
        pivot={"x": 1, "y": 1},
    )

    assert result["bounds"] == rect(3, 3, 4, 4)
    assert result["pivot"] == {"x": 1, "y": 1}


async def test_update_slice_unknown_name_errors(call):
    await setup(call)

    with pytest.raises(ToolError, match="slice 'Ghost' not found"):
        await call("update_slice", path="a.aseprite", name="Ghost", rect=rect(0, 0, 2, 2))


async def test_delete_slice(call):
    await setup(
        call,
        op("create_slice", name="A", rect=rect(0, 0, 2, 2)),
        op("create_slice", name="B", rect=rect(0, 0, 2, 2)),
    )

    await call("delete_slice", path="a.aseprite", name="A")

    assert [s["name"] for s in (await call("list_slices", path="a.aseprite"))["slices"]] == ["B"]


# tilemaps


def tile(col: int, row: int, index: int) -> dict:
    return {"col": col, "row": row, "index": index}


def square(color: str, size: int) -> list[dict]:
    return [{"x": x, "y": y, "color": color} for y in range(size) for x in range(size)]


async def test_get_tilemap_info_on_new_layer(call):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))

    result = await call("get_tilemap_info", path="a.aseprite", layer="Floor")

    assert result["tile_size"] == {"w": 4, "h": 4}
    assert result["tile_count"] == 1
    assert result["grid"] == {"columns": 2, "rows": 2}
    assert result["cel"] is None
    assert result["tiles"] == [[0, 0], [0, 0]]


async def test_set_tiles_round_trip(call):
    await setup(
        call,
        op("add_layer", name="Floor", kind="tilemap", tile_size=4),
        op("draw_tile", layer="Floor", tile_index=1, pixels=square(RED, 4)),
    )

    await call("set_tiles", path="a.aseprite", layer="Floor", frame=1, tiles=[tile(1, 0, 1)])

    result = await call("get_tilemap_info", path="a.aseprite", layer="Floor")
    assert result["tiles"] == [[0, 1], [0, 0]]


async def test_draw_tile_shows_where_the_tile_is_placed(call, pixels, tmp_path: Path):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))

    result = await call(
        "draw_tile",
        path="a.aseprite",
        layer="Floor",
        tile_index=1,
        pixels=[{"x": 1, "y": 2, "color": BLUE}],
    )
    await call("set_tiles", path="a.aseprite", layer="Floor", frame=1, tiles=[tile(1, 1, 1)])

    assert result["tile_count"] == 2
    read = await call("read_pixels", path="a.aseprite", rect=rect(5, 6, 1, 1), format="hex")
    assert read["rows"] == [BLUE]


async def test_two_tilemaps_different_tile_size(call):
    await setup(
        call,
        op("add_layer", name="Big", kind="tilemap", tile_size=8),
        op("add_layer", name="Small", kind="tilemap", tile_size=2),
        op("draw_tile", layer="Small", tile_index=1, pixels=square(RED, 2)),
        op("draw_tile", layer="Big", tile_index=1, pixels=square(BLUE, 8)),
    )

    await call("set_tiles", path="a.aseprite", layer="Small", frame=1, tiles=[tile(3, 2, 1)])
    await call("set_tiles", path="a.aseprite", layer="Big", frame=1, tiles=[tile(0, 0, 1)])

    small = await call("get_tilemap_info", path="a.aseprite", layer="Small", rect=rect(2, 2, 2, 1))
    big = await call("get_tilemap_info", path="a.aseprite", layer="Big")
    assert (small["tile_size"], small["grid"]) == ({"w": 2, "h": 2}, {"columns": 4, "rows": 4})
    assert small["tiles"] == [[0, 1]]
    assert (big["tile_size"], big["grid"]) == ({"w": 8, "h": 8}, {"columns": 1, "rows": 1})
    assert big["tiles"] == [[1]]
    read = await call("read_pixels", path="a.aseprite", rect=rect(6, 4, 2, 2), format="hex")
    assert read["rows"] == ["#ff0000 #ff0000", "#ff0000 #ff0000"]


async def test_set_tiles_index_out_of_range_errors(call):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))

    with pytest.raises(ToolError, match="tile index 3 is out of range: the tileset has 1 tile"):
        await call("set_tiles", path="a.aseprite", layer="Floor", frame=1, tiles=[tile(0, 0, 3)])


async def test_set_tiles_outside_the_grid_errors(call):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))

    with pytest.raises(ToolError, match=r"cell \(2, 0\) is outside the 2x2 grid"):
        await call("set_tiles", path="a.aseprite", layer="Floor", frame=1, tiles=[tile(2, 0, 0)])


async def test_set_tiles_limit(call):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))

    with pytest.raises(ToolError, match="4096"):
        await call(
            "set_tiles", path="a.aseprite", layer="Floor", frame=1, tiles=[tile(0, 0, 0)] * 4097
        )


async def test_tile_tools_refuse_image_layer(call):
    await setup(call)

    with pytest.raises(ToolError, match="'Layer 1' is not a tilemap layer"):
        await call("get_tilemap_info", path="a.aseprite", layer="Layer 1")


async def test_set_tiles_refuses_locked_layer(call, locks, tmp_path: Path):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))
    await locks(tmp_path / "a.aseprite", lock=["Floor"])

    with pytest.raises(ToolError, match="'Floor' is locked"):
        await call("set_tiles", path="a.aseprite", layer="Floor", frame=1, tiles=[tile(0, 0, 0)])


async def test_draw_tile_pixel_outside_tile_errors(call):
    await setup(call, op("add_layer", name="Floor", kind="tilemap", tile_size=4))

    with pytest.raises(ToolError, match=r"pixel \(4, 0\) is outside the 4x4 tile"):
        await call(
            "draw_tile",
            path="a.aseprite",
            layer="Floor",
            tile_index=1,
            pixels=[{"x": 4, "y": 0, "color": RED}],
        )


async def test_new_tools_run_in_one_batch(call):
    await setup(call)
    entries = [
        op("repair_animation", ensure_layers=["Fx"]),
        op("add_layer", name="Floor", kind="tilemap", tile_size=4),
        op("draw_tile", layer="Floor", tile_index=1, pixels=square(RED, 4)),
        op("set_tiles", layer="Floor", frame=1, tiles=[tile(0, 0, 1)]),
        op("get_tilemap_info", layer="Floor", rect=rect(0, 0, 1, 1)),
        op("create_slice", name="S", rect=rect(0, 0, 2, 2)),
        op("update_slice", name="S", rect=rect(1, 1, 2, 2)),
        op("list_slices"),
        op("check_animation", required_layers=["Fx"]),
        op("delete_slice", name="S"),
    ]

    result = (await call("batch", path="a.aseprite", ops=entries))["result"]

    assert result[0]["created"] == ["Fx"]
    assert result[4]["tiles"] == [[1]]
    assert result[7]["slices"][0]["bounds"] == rect(1, 1, 2, 2)
    assert result[8]["ok"] is True


async def test_copy_layers_runs_in_batch(call):
    await source_sprite(call, dot(0, 0, "Ink"))
    await setup(call, name="dst.aseprite")

    result = await call(
        "batch",
        path="dst.aseprite",
        ops=[op("copy_layers", source="src.aseprite", layers=["Ink"]), dot(1, 1, "Ink")],
    )

    assert result["result"][0]["layers"] == ["Ink"]


async def test_copy_layers_from_numbered_png_takes_one_frame(call, tmp_path: Path):
    for i in (1, 2):
        await call("create_sprite", path=f"src_{i}.png", width=8, height=8, background="#ff0000")
    await setup(call, name="dst.aseprite")

    result = await call("copy_layers", source="src_1.png", target="dst.aseprite", layers=["Layer"])

    assert result["frames_added"] == 0
    info = await call("get_sprite_info", path="dst.aseprite")
    assert len(info["frames"]) == 1
