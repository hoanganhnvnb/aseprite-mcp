from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.errors import ToolError
from helpers import sprite_maker

RED = [255, 0, 0, 255]
BLUE = [0, 0, 255, 255]
CLEAR = [0, 0, 0, 0]


new_sprite = sprite_maker(16, 16)


async def fill_frames(call, pixels, path: Path, frames: int) -> None:
    """Canvas-sized cels at (0, 0) with a red pixel, independent in every frame."""
    await new_sprite(call, frames=frames)
    await pixels(path, put=[(1, 1, *RED)])
    if frames > 1:
        await call("copy_frames", path="a.aseprite", source=1, targets=f"2-{frames}")


def xs(cels: list) -> list[int]:
    return [cel["x"] for cel in cels]


async def test_set_cel_missing_cel_fails(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="'Layer 1' has no cel in frame 2"):
        await call("set_cel", path="a.aseprite", layer="Layer 1", frames=2, x=3)


async def test_set_cel_create_makes_empty_cel(call, cels, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)

    result = await call(
        "set_cel", path="a.aseprite", layer="Layer 1", frames=2, x=4, y=5, create=True
    )

    assert result["created"] == 1
    cel = (await cels(path))[1]
    assert (cel["x"], cel["y"]) == (4, 5)
    assert await pixels(path, read=[(4, 5)], frame=2) == [CLEAR]


async def test_set_cel_create_on_tilemap_layer(call, cels, tmp_path: Path):
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Tiles", kind="tilemap", tile_size=4)

    await call("set_cel", path="a.aseprite", layer="Tiles", frames=2, z_index=1, create=True)

    assert (await cels(tmp_path / "a.aseprite", layer="Tiles"))[1]["z_index"] == 1


async def test_set_cel_relative_offset(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=2)

    await call("set_cel", path="a.aseprite", layer="Layer 1", frames="all", x=-3, relative=True)

    assert xs(await cels(path)) == [-3, -3]
    assert await pixels(path, read=[(-2, 1)], frame=2) == [RED]


async def test_set_cel_absolute_keeps_other_axis(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=1)

    await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, y=7)

    cel = (await cels(path))[0]
    assert (cel["x"], cel["y"]) == (0, 7)


async def test_set_cel_opacity_and_z_index(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=2)

    await call("set_cel", path="a.aseprite", layer="Layer 1", frames=2, opacity=90, z_index=-1)

    first, second = await cels(path)
    assert (first["opacity"], first["z_index"]) == (255, 0)
    assert (second["opacity"], second["z_index"]) == (90, -1)


async def test_set_cel_requires_a_change(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="nothing to change"):
        await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, relative=True)


async def test_clear_cels_refuses_the_background_layer(call, pixels, tmp_path: Path):
    await new_sprite(call, background="#ffffff")
    await pixels(tmp_path / "a.aseprite", background=True)

    with pytest.raises(ToolError, match="cel tools cannot change its cels"):
        await call("clear_cels", path="a.aseprite", layer="Background", frames=1)


async def test_set_cel_unlinks_cels_outside_the_range(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=3)
    await pixels(path, put=[(1, 1, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)

    await call("set_cel", path="a.aseprite", layer="Layer 1", frames=2, x=6)

    assert xs(await cels(path)) == [0, 6, 0]


async def test_set_cel_refuses_group(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")

    with pytest.raises(ToolError, match="'G' is a group"):
        await call("set_cel", path="a.aseprite", layer="G", frames=1, x=1)


async def test_clear_cels_removes_cels_and_ignores_missing(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=3)
    await pixels(path, put=[(1, 1, *RED)])
    await pixels(path, put=[(1, 1, *RED)], frame=3)

    result = await call("clear_cels", path="a.aseprite", layer="Layer 1", frames="all")

    assert result["removed"] == 2
    assert await cels(path) == [False, False, False]


async def test_clear_cels_refuses_group(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")

    with pytest.raises(ToolError, match="'G' is a group"):
        await call("clear_cels", path="a.aseprite", layer="G", frames=1)


async def test_tween_position_linear(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=5)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="1-5",
        property="position",
        start={"x": 0, "y": 0},
        end={"x": 8, "y": 0},
    )

    assert xs(await cels(path)) == [0, 2, 4, 6, 8]


async def test_tween_position_ease_in_is_slower_at_start(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=5)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="all",
        property="position",
        start={"x": 0, "y": 0},
        end={"x": 16, "y": 0},
        easing="ease_in",
    )

    assert xs(await cels(path)) == [0, 1, 4, 9, 16]


async def test_tween_loop_excludes_end(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=4)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="1-4",
        property="position",
        start={"x": 0, "y": 0},
        end={"x": 8, "y": 0},
        loop=True,
    )

    assert xs(await cels(path)) == [0, 2, 4, 6]


async def test_tween_opacity(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=3)

    result = await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="all",
        property="opacity",
        start=255,
        end=0,
    )

    assert [cel["opacity"] for cel in await cels(path)] == [255, 128, 0]
    assert result["values"][1] == {"frame": 2, "opacity": 128}


async def test_tween_scale_doubles_cel_size_nearest_neighbour(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(4, 4, *RED), (5, 4, *BLUE)])

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="1-2",
        property="scale",
        start=1,
        end=2,
        anchor="top_left",
    )

    first, second = await cels(path)
    assert (first["width"], first["height"]) == (2, 1)
    assert (second["x"], second["y"], second["width"], second["height"]) == (4, 4, 4, 2)
    row = await pixels(path, read=[(4, 5), (5, 5), (6, 5), (7, 5)], frame=2)
    assert row == [RED, RED, BLUE, BLUE]


async def test_tween_scale_center_anchor_keeps_center(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(4, 4, *RED), (5, 5, *RED)])

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="1-2",
        property="scale",
        start=1,
        end={"x": 2, "y": 3},
    )

    second = (await cels(path))[1]
    assert (second["x"], second["y"], second["width"], second["height"]) == (3, 2, 4, 6)


async def test_tween_scale_center_anchor_rounds_the_offset_not_the_position(
    call, pixels, cels, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(0, 0, *RED), (3, 3, *RED)])
    await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, x=-3)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="1-2",
        property="scale",
        start=1,
        end=0.75,
    )

    second = (await cels(path))[1]
    assert (second["x"], second["y"], second["width"], second["height"]) == (-2, 1, 3, 3)


async def test_tween_scale_unlinks_shared_cels(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=3)
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(4, 4, *RED), (5, 5, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="2-3",
        property="scale",
        start=2,
        end=3,
        source_frame=1,
    )

    first, second, third = await cels(path)
    assert (first["width"], second["width"], third["width"]) == (2, 4, 6)
    assert len({first["image_id"], second["image_id"], third["image_id"]}) == 3


async def test_tween_scale_on_indexed_keeps_indices(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=2, color_mode="indexed")
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(0, 0, *RED), (1, 0, 0, 0, 0, 255)])
    before = await pixels(path, read=[(0, 0), (1, 0)], values=True)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="all",
        property="scale",
        start=1,
        end=2,
        anchor="top_left",
    )

    after = await pixels(path, read=[(0, 0), (1, 0), (2, 0), (3, 1)], frame=2, values=True)
    assert after == [before[0], before[0], before[1], before[1]]


async def test_tween_scale_too_large_fails(call):
    await new_sprite(call, frames=2)
    await call("resize_sprite", path="a.aseprite", width=512, height=512)

    with pytest.raises(ToolError, match="8192x8192, larger than 4096x4096"):
        await call(
            "tween_cels",
            path="a.aseprite",
            layer="Layer 1",
            frames="all",
            property="scale",
            start=1,
            end=16,
        )


async def test_tween_needs_two_frames(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="at least 2 frames"):
        await call(
            "tween_cels",
            path="a.aseprite",
            layer="Layer 1",
            frames=1,
            property="opacity",
            start=0,
            end=255,
        )


async def test_tween_position_needs_points(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="position needs start and end as"):
        await call(
            "tween_cels",
            path="a.aseprite",
            layer="Layer 1",
            frames="all",
            property="position",
            start=0,
            end=8,
        )


async def test_tween_position_missing_cel_fails(call):
    await new_sprite(call, frames=3)

    with pytest.raises(ToolError, match="no cel in frame 2"):
        await call(
            "tween_cels",
            path="a.aseprite",
            layer="Layer 1",
            frames="all",
            property="position",
            start={"x": 0, "y": 0},
            end={"x": 4, "y": 4},
        )


async def test_oscillate_not_cumulative(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=4)
    args = {"layer": "Layer 1", "frames": "all", "amplitude_y": 3, "phase": 0.25}

    await call("oscillate_cels", path="a.aseprite", **args)
    once = await cels(path)
    await call("oscillate_cels", path="a.aseprite", **args)

    assert await cels(path) == once
    assert [cel["y"] for cel in once] == [0, -3, -6, -3]


async def test_oscillate_closes_loop(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=4)

    result = await call(
        "oscillate_cels", path="a.aseprite", layer="Layer 1", frames="all", amplitude_x=4
    )

    assert xs(await cels(path)) == [0, 4, 0, -4]
    assert [cel["y"] for cel in await cels(path)] == [0, 0, 0, 0]
    assert result["positions"][3] == {"frame": 4, "x": -4, "y": 0}


async def test_oscillate_needs_an_amplitude(call):
    await new_sprite(call, frames=2)

    with pytest.raises(ToolError, match="amplitude"):
        await call("oscillate_cels", path="a.aseprite", layer="Layer 1", frames="all")


async def test_cel_tools_in_one_batch(call, pixels, cels, tmp_path: Path, monkeypatch):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=3)
    calls = []
    real_run_script = ops.run_script

    async def counting_run_script(*args, **kwargs):
        calls.append(args[0])
        return await real_run_script(*args, **kwargs)

    monkeypatch.setattr(ops, "run_script", counting_run_script)

    await call(
        "batch",
        path="a.aseprite",
        ops=[
            {"tool": "set_cel", "args": {"layer": "Layer 1", "frames": "all", "opacity": 100}},
            {
                "tool": "tween_cels",
                "args": {
                    "layer": "Layer 1",
                    "frames": "1-2",
                    "property": "position",
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 2, "y": 2},
                },
            },
            {
                "tool": "oscillate_cels",
                "args": {"layer": "Layer 1", "frames": "2-3", "amplitude_x": 1},
            },
            {"tool": "clear_cels", "args": {"layer": "Layer 1", "frames": 3}},
        ],
    )

    assert len(calls) == 1
    first, second, third = await cels(path)
    assert (first["x"], first["opacity"]) == (0, 100)
    assert (second["x"], second["y"]) == (2, 2)
    assert third is False


async def test_tween_position_splits_linked_cels(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, frames=3)
    await pixels(path, put=[(1, 1, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)

    await call(
        "tween_cels",
        path="a.aseprite",
        layer="Layer 1",
        frames="all",
        property="position",
        start={"x": 0, "y": 0},
        end={"x": -4, "y": 2},
    )

    assert [(cel["x"], cel["y"]) for cel in await cels(path)] == [(0, 0), (-2, 1), (-4, 2)]


async def test_tween_scale_refuses_tilemap_layer(call):
    await new_sprite(call, frames=2)
    await call("add_layer", path="a.aseprite", name="Tiles", kind="tilemap", tile_size=4)
    await call("set_cel", path="a.aseprite", layer="Tiles", frames=1, x=0, create=True)

    with pytest.raises(ToolError, match="tilemap layer 'Tiles'"):
        await call(
            "tween_cels",
            path="a.aseprite",
            layer="Tiles",
            frames="all",
            property="scale",
            start=1,
            end=2,
        )


async def test_oscillate_all_frames_of_single_frame_sprite_fails(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="at least 2 frames, got 1"):
        await call(
            "oscillate_cels", path="a.aseprite", layer="Layer 1", frames="all", amplitude_x=2
        )


async def test_set_cel_refuses_locked_layer(call, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await locks(path, lock=["Layer 1"])
    before = path.read_bytes()

    with pytest.raises(ToolError, match="'Layer 1' is locked; unlock it first"):
        await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, x=3)

    assert path.read_bytes() == before


async def test_set_cel_refuses_layer_in_locked_group(call, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")
    await call("update_layer", path="a.aseprite", layer="Layer 1", parent="G")
    await locks(path, lock=["G"])

    with pytest.raises(ToolError, match="'G/Layer 1' is inside the locked group 'G'"):
        await call("set_cel", path="a.aseprite", layer="Layer 1", frames=1, opacity=10)


async def test_clear_cels_refuses_locked_layer(call, pixels, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(1, 1, *RED)])
    await locks(path, lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call("clear_cels", path="a.aseprite", layer="Layer 1", frames="all")

    assert await pixels(path, read=[(1, 1)]) == [RED]


async def test_tween_cels_refuses_locked_layer(call, pixels, cels, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=3)
    await locks(path, lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call(
            "tween_cels",
            path="a.aseprite",
            layer="Layer 1",
            frames="all",
            property="position",
            start={"x": 0, "y": 0},
            end={"x": 4, "y": 0},
        )

    assert xs(await cels(path)) == [0, 0, 0]


async def test_oscillate_cels_refuses_locked_layer(call, pixels, cels, locks, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await fill_frames(call, pixels, path, frames=4)
    await locks(path, lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call(
            "oscillate_cels", path="a.aseprite", layer="Layer 1", frames="all", amplitude_x=2
        )

    assert xs(await cels(path)) == [0, 0, 0, 0]
