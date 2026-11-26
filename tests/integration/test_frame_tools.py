from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.errors import ToolError
from helpers import sprite_maker

RED = [255, 0, 0, 255]
CLEAR = [0, 0, 0, 0]
BLUE = [0, 0, 255, 255]


new_sprite = sprite_maker(8, 8)


async def durations(call) -> list[int]:
    info = await call("get_sprite_info", path="a.aseprite")
    return [frame["duration_ms"] for frame in info["frames"]]


async def test_add_frames_are_empty_by_default(call, pixels, cels, tmp_path: Path):
    await new_sprite(call)
    await pixels(tmp_path / "a.aseprite", put=[(1, 1, *RED)])

    result = await call("add_frames", path="a.aseprite")

    assert result == {"frames": [2], "frame_count": 2}
    assert (await cels(tmp_path / "a.aseprite"))[1] is False


async def test_add_frames_copy_content(call, pixels, tmp_path: Path):
    await new_sprite(call)
    await pixels(tmp_path / "a.aseprite", put=[(1, 1, *RED)])

    result = await call("add_frames", path="a.aseprite", count=2, copy_content=True)

    assert result["frames"] == [2, 3]
    assert await pixels(tmp_path / "a.aseprite", read=[(1, 1)], frame=3) == [RED]


async def test_add_frames_after_inserts_in_the_middle(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=3)
    await pixels(path, put=[(0, 0, *BLUE)], frame=3)

    result = await call("add_frames", path="a.aseprite", after=1)

    assert result == {"frames": [2], "frame_count": 4}
    assert (await cels(path))[1] is False
    assert await pixels(path, read=[(0, 0)], frame=4) == [BLUE]


async def test_add_frames_at_the_start(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])

    result = await call("add_frames", path="a.aseprite", after=0)

    assert result["frames"] == [1]
    assert await pixels(path, read=[(0, 0)], frame=2) == [RED]


async def test_add_frames_after_past_the_end_fails(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="after=5"):
        await call("add_frames", path="a.aseprite", after=5)


async def test_add_frames_sets_duration(call):
    await new_sprite(call)

    await call("add_frames", path="a.aseprite", count=2, duration_ms=250)

    assert await durations(call) == [100, 250, 250]


async def test_add_frames_keeps_duration_of_previous_frame(call):
    await new_sprite(call)
    await call("set_frame_duration", path="a.aseprite", duration_ms=40)

    await call("add_frames", path="a.aseprite")

    assert await durations(call) == [40, 40]


async def test_delete_frames_refuses_removing_all(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="at least one frame"):
        await call("delete_frames", path="a.aseprite", frames="all")


async def test_delete_frames_removes_requested(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=4)
    await pixels(path, put=[(0, 0, *BLUE)], frame=4)

    result = await call("delete_frames", path="a.aseprite", frames="1-2")

    assert result == {"deleted": [1, 2], "frame_count": 2}
    assert await pixels(path, read=[(0, 0)], frame=2) == [BLUE]


async def test_delete_frames_out_of_range_fails(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="frame 3 is out of range"):
        await call("delete_frames", path="a.aseprite", frames=3)


async def test_set_frame_duration_all_and_range(call):
    await new_sprite(call, frames=3)

    await call("set_frame_duration", path="a.aseprite", duration_ms=200)
    result = await call("set_frame_duration", path="a.aseprite", duration_ms=50, frames="2-3")

    assert result == {"frames": [2, 3], "duration_ms": 50}
    assert await durations(call) == [200, 50, 50]


async def test_set_frame_duration_rejects_bad_range(call):
    await new_sprite(call, frames=3)

    with pytest.raises(ToolError, match="'3-1'"):
        await call("set_frame_duration", path="a.aseprite", duration_ms=50, frames="3-1")


async def test_copy_frames_includes_group_children(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call(
        "batch",
        path="a.aseprite",
        ops=[
            {"tool": "add_layer", "args": {"name": "Body", "kind": "group"}},
            {"tool": "add_layer", "args": {"name": "Arms", "kind": "group", "parent": "Body"}},
            {"tool": "add_layer", "args": {"name": "Left", "parent": "Body/Arms"}},
        ],
    )
    await pixels(path, put=[(2, 3, *RED)], layer="Body/Arms/Left")

    result = await call("copy_frames", path="a.aseprite", source=1, targets="2")

    assert "Body/Arms/Left" in result["layers"]
    assert await pixels(path, read=[(2, 3)], layer="Body/Arms/Left", frame=2) == [RED]


async def test_copy_frames_unknown_layer_fails(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="layer 'Ghost' not found"):
        await call(
            "copy_frames", path="a.aseprite", source=1, targets="2", layers=["Layer 1", "Ghost"]
        )


async def test_copy_frames_only_given_layers(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Ink")
    await pixels(path, put=[(0, 0, *RED)], layer="Ink")

    result = await call("copy_frames", path="a.aseprite", source=1, targets="2", layers=["Ink"])

    assert result["layers"] == ["Ink"]
    assert await pixels(path, read=[(0, 0)], layer="Ink", frame=2) == [RED]
    assert (await cels(path, layer="Layer 1"))[1] is False


async def test_copy_frames_missing_only_keeps_existing_cels(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Ink")
    await pixels(path, put=[(0, 0, *RED)])
    await pixels(path, put=[(0, 0, *BLUE)], frame=2)
    await pixels(path, put=[(1, 1, *RED)], layer="Ink")

    await call("copy_frames", path="a.aseprite", source=1, targets="2", mode="missing_only")

    assert await pixels(path, read=[(0, 0)], frame=2) == [BLUE]
    assert await pixels(path, read=[(1, 1)], layer="Ink", frame=2) == [RED]


async def test_copy_frames_replace_clears_target_when_source_is_empty(
    call, pixels, cels, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Ink")
    await pixels(path, put=[(0, 0, *BLUE)], layer="Ink", frame=2)

    result = await call("copy_frames", path="a.aseprite", source=1, targets="2", layers=["Ink"])

    assert result["cels_cleared"] == 1
    assert (await cels(path, layer="Ink"))[1] is False


async def test_copy_frames_append_creates_frames(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])

    result = await call("copy_frames", path="a.aseprite", source=1, targets="append:2")

    assert result["frames"] == [2, 3]
    assert len(await durations(call)) == 3
    assert await pixels(path, read=[(0, 0)], frame=3) == [RED]


async def test_copy_frames_skips_source_in_targets(call):
    await new_sprite(call, frames=3)

    result = await call("copy_frames", path="a.aseprite", source=2, targets="all")

    assert result["frames"] == [1, 3]


async def test_copy_frames_missing_source_fails(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="source frame 3"):
        await call("copy_frames", path="a.aseprite", source=3, targets="1")


async def test_copy_frames_keeps_position_and_opacity(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Ink")
    await pixels(path, put=[(5, 6, *RED)], layer="Ink")
    await cels(path, layer="Ink", update=[(1, 128, 2)])

    await call("copy_frames", path="a.aseprite", source=1, targets="2")

    copy = (await cels(path, layer="Ink"))[1]
    assert (copy["x"], copy["y"], copy["opacity"], copy["z_index"]) == (5, 6, 128, 2)


async def test_copy_frames_makes_independent_copies(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await pixels(path, put=[(0, 0, *RED)])

    await call("copy_frames", path="a.aseprite", source=1, targets="2")

    first, second = await cels(path)
    assert first["image_id"] != second["image_id"]


async def test_copy_frames_link_shares_image(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=3)
    await pixels(path, put=[(0, 0, *RED)])

    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)

    ids = {cel["image_id"] for cel in await cels(path)}
    assert len(ids) == 1
    assert await pixels(path, read=[(0, 0)], frame=3) == [RED]


async def test_copy_frames_refuses_layer_in_locked_group(call, pixels, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="G", kind="group")
    await call("add_layer", path="a.aseprite", name="C", parent="G")
    await pixels(path, put=[(0, 0, *RED)], layer="G/C")
    await locks(path, lock=["G"])

    with pytest.raises(ToolError, match="'G/C' is inside the locked group 'G'"):
        await call("copy_frames", path="a.aseprite", source=1, targets="2", link=True)

    assert await pixels(path, read=[(0, 0)], layer="G/C", frame=2) == [CLEAR]


async def test_copy_frames_refuses_a_group_with_no_layers(call, tmp_path: Path):
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="G", kind="group")

    with pytest.raises(ToolError, match="group 'G' has no layers to copy"):
        await call("copy_frames", path="a.aseprite", source=1, targets="append:2", layers=["G"])

    info = await call("get_sprite_info", path="a.aseprite")
    assert len(info["frames"]) == 2


async def test_copy_frames_refuses_locked_layer(call, pixels, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await pixels(path, put=[(0, 0, *RED)])
    await locks(path, lock=["Layer 1"])
    before = path.read_bytes()

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call("copy_frames", path="a.aseprite", source=1, targets="append:1")

    assert path.read_bytes() == before


async def test_copy_frames_passes_over_locked_layer_with_nothing_to_copy(
    call, pixels, locks, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Empty")
    await pixels(path, put=[(0, 0, *RED)])
    await locks(path, lock=["Empty"])

    await call("copy_frames", path="a.aseprite", source=1, targets="2")

    assert await pixels(path, read=[(0, 0)], frame=2) == [RED]


async def test_copy_frames_on_indexed_sprite_keeps_indices(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2, color_mode="indexed")
    await pixels(path, put=[(1, 1, 172, 50, 50, 255), (2, 2, 0, 0, 0, 255)])
    original = await pixels(path, read=[(1, 1), (2, 2), (3, 3)], values=True)

    await call("copy_frames", path="a.aseprite", source=1, targets="2")

    assert await pixels(path, read=[(1, 1), (2, 2), (3, 3)], frame=2, values=True) == original


async def test_set_tag_roundtrip(call):
    await new_sprite(call, frames=4)

    result = await call(
        "set_tag",
        path="a.aseprite",
        name='walk "left"/a',
        from_frame=2,
        to_frame=4,
        direction="pingpong",
        repeat=3,
    )

    assert result["created"] is True
    info = await call("get_sprite_info", path="a.aseprite")
    assert info["tags"] == [
        {
            "name": 'walk "left"/a',
            "from_frame": 2,
            "to_frame": 4,
            "direction": "pingpong",
            "repeats": 3,
        }
    ]


async def test_set_tag_updates_existing(call):
    await new_sprite(call, frames=4)
    await call("set_tag", path="a.aseprite", name="idle", from_frame=1, to_frame=2)

    result = await call(
        "set_tag", path="a.aseprite", name="idle", from_frame=3, to_frame=4, direction="reverse"
    )

    assert result["created"] is False
    info = await call("get_sprite_info", path="a.aseprite")
    assert [(t["name"], t["from_frame"], t["to_frame"], t["direction"]) for t in info["tags"]] == [
        ("idle", 3, 4, "reverse")
    ]


async def test_set_tag_past_last_frame_fails(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="to_frame 3"):
        await call("set_tag", path="a.aseprite", name="idle", from_frame=1, to_frame=3)


async def test_set_tag_backwards_fails(call):
    await new_sprite(call, frames=3)

    with pytest.raises(ToolError, match="from_frame"):
        await call("set_tag", path="a.aseprite", name="idle", from_frame=3, to_frame=1)


async def test_delete_tag_removes_it(call):
    await new_sprite(call, frames=2)
    await call("set_tag", path="a.aseprite", name="idle", from_frame=1, to_frame=2)

    result = await call("delete_tag", path="a.aseprite", name="idle")

    assert result == {"deleted": "idle", "tags_left": 0}


async def test_delete_tag_unknown_fails(call):
    await new_sprite(call, frames=2)
    await call("set_tag", path="a.aseprite", name="idle", from_frame=1, to_frame=2)

    with pytest.raises(ToolError, match="tag 'Idle' not found"):
        await call("delete_tag", path="a.aseprite", name="Idle")


async def test_frame_tools_in_one_batch(call, monkeypatch: pytest.MonkeyPatch):
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
            {"tool": "add_frames", "args": {"count": 3}},
            {"tool": "set_frame_duration", "args": {"duration_ms": 80, "frames": "2-4"}},
            {"tool": "copy_frames", "args": {"source": 1, "targets": "append:1"}},
            {"tool": "set_tag", "args": {"name": "run", "from_frame": 2, "to_frame": 5}},
            {"tool": "delete_frames", "args": {"frames": 1}},
        ],
    )

    assert len(calls) == 1
    assert result["result"][4] == {"deleted": [1], "frame_count": 4}
    info = await call("get_sprite_info", path="a.aseprite")
    assert [f["duration_ms"] for f in info["frames"]] == [80, 80, 80, 80]
    assert (info["tags"][0]["from_frame"], info["tags"][0]["to_frame"]) == (1, 4)
