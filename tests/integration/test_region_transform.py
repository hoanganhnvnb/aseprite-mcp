from pathlib import Path

import pytest

from aseprite_mcp import ops
from aseprite_mcp.errors import ToolError
from helpers import rect, sprite_maker

RED = [255, 0, 0, 255]
BLUE = [0, 0, 255, 255]
GREEN = [0, 255, 0, 255]
WHITE = [255, 255, 255, 255]
CLEAR = [0, 0, 0, 0]


new_sprite = sprite_maker(8, 8)


async def trimmed(call, pixels, path: Path, *points: tuple[int, int]) -> None:
    """Replaces the cel of Layer 1 in frame 1 by one that just covers red points."""
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=1)
    await pixels(path, put=[(x, y, *RED) for x, y in points])


async def linked_frames(call, pixels, path: Path) -> None:
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    await pixels(path, put=[(1, 1, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3", link=True)


async def test_move_region_moves_pixels_and_clears_source(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 8, 4)
    await pixels(path, put=[(1, 1, *RED), (2, 1, *RED)])

    result = await call(
        "move_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 2, 1), dx=3, dy=1
    )

    assert result == {
        "layer": "Layer 1",
        "frame": 1,
        "target_layer": "Layer 1",
        "target_frame": 1,
        "rect": rect(1, 1, 2, 1),
        "moved": 2,
        "clipped": 0,
    }
    assert await grid(path) == [
        "........",
        "........",
        "....##..",
        "........",
    ]


async def test_move_region_overlapping_destination(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(1, 1, *RED), (2, 1, *BLUE), (3, 1, *GREEN)])

    await call("move_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 3, 1), dx=1, dy=0)

    assert await pixels(path, read=[(1, 1), (2, 1), (3, 1), (4, 1)]) == [CLEAR, RED, BLUE, GREEN]


async def test_move_region_overwrites_destination_with_transparent_pixels(
    call, pixels, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(1, 1, *RED), (4, 1, *BLUE)])

    await call("move_region", path="a.aseprite", layer="Layer 1", rect=rect(0, 1, 2, 1), dx=3, dy=0)

    assert await pixels(path, read=[(3, 1), (4, 1)]) == [CLEAR, RED]


async def test_move_region_blend_composites(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(1, 1, 255, 0, 0, 128), (3, 1, *BLUE), (4, 1, *BLUE)])

    await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(0, 1, 2, 1),
        dx=3,
        dy=0,
        blend=True,
    )

    assert await pixels(path, read=[(1, 1), (3, 1), (4, 1)]) == [
        CLEAR,
        BLUE,
        [128, 0, 127, 255],
    ]


async def test_copy_region_source_untouched(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="Top")
    await trimmed(call, pixels, path, (2, 2), (3, 3))
    before = await cels(path, layer="Layer 1")

    await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(2, 2, 2, 2),
        dx=3,
        dy=0,
        copy=True,
        target_layer="Top",
    )

    assert await cels(path, layer="Layer 1") == before
    assert await pixels(path, read=[(2, 2), (3, 3)]) == [RED, RED]
    assert await pixels(path, read=[(5, 2), (6, 3), (2, 2)], layer="Top") == [RED, RED, CLEAR]


async def test_copy_region_within_the_layer_stamps_a_second_copy(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(1, 1, *RED)])

    await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(1, 1, 1, 1),
        dx=4,
        dy=4,
        copy=True,
    )

    assert await pixels(path, read=[(1, 1), (5, 5)]) == [RED, RED]


async def test_move_region_to_other_layer_and_frame(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await call("add_layer", path="a.aseprite", name="Top")
    await pixels(path, put=[(1, 1, *RED)])

    result = await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(1, 1, 1, 1),
        dx=2,
        dy=0,
        target_layer="Top",
        target_frame=2,
    )

    assert (result["target_layer"], result["target_frame"]) == ("Top", 2)
    assert await pixels(path, read=[(1, 1)]) == [CLEAR]
    assert await pixels(path, read=[(3, 1)], layer="Top", frame=2) == [RED]
    first, second = await cels(path, layer="Top")
    assert first is False
    assert (second["x"], second["y"], second["width"], second["height"]) == (3, 1, 1, 1)


async def test_move_region_grows_cel_for_destination_outside_it(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await trimmed(call, pixels, path, (1, 1))

    await call("move_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 1, 1), dx=5, dy=4)

    assert await pixels(path, read=[(1, 1), (6, 5)]) == [CLEAR, RED]
    cel = (await cels(path))[0]
    assert (cel["x"], cel["y"], cel["width"], cel["height"]) == (1, 1, 6, 5)


async def test_move_region_clips_at_canvas_edge_and_counts(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(5, 0, *RED), (6, 0, *BLUE), (7, 0, *GREEN)])

    result = await call(
        "move_region", path="a.aseprite", layer="Layer 1", rect=rect(5, 0, 3, 1), dx=2, dy=0
    )

    assert (result["moved"], result["clipped"]) == (1, 2)
    assert await pixels(path, read=[(5, 0), (6, 0), (7, 0)]) == [CLEAR, CLEAR, RED]
    assert (await cels(path))[0]["width"] == 8


async def test_move_region_huge_rect_is_clipped_to_the_canvas(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])

    result = await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(-60000, -60000, 120000, 120000),
        dx=1,
        dy=0,
    )

    assert result["rect"] == rect(0, 0, 8, 8)
    assert (result["moved"], result["clipped"]) == (56, 8)
    assert await pixels(path, read=[(0, 0), (1, 0)]) == [CLEAR, RED]


async def test_move_region_outside_canvas_fails(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="outside the canvas"):
        await call(
            "move_region", path="a.aseprite", layer="Layer 1", rect=rect(8, 0, 2, 2), dx=-4, dy=0
        )


async def test_move_region_indexed_keeps_pixels(call, pixels, set_palette, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (10, 10, 10, 255), (255, 0, 0, 255)])
    await pixels(path, put=[(1, 1, *RED)])
    # Index 1 now has the same colour as index 2; decoding to RGBA would pick 1.
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (255, 0, 0, 255)])

    await call("move_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 1, 1), dx=2, dy=0)

    assert await pixels(path, read=[(1, 1), (3, 1)], values=True) == [0, 2]


async def test_move_region_grayscale(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="grayscale")
    await pixels(path, put=[(1, 1, 100, 100, 100, 128)])

    await call("move_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 1, 1), dx=0, dy=3)

    assert await pixels(path, read=[(1, 1), (1, 4)]) == [CLEAR, [100, 100, 100, 128]]


async def test_move_region_refuses_locked_layer(call, locks, tmp_path: Path):
    await new_sprite(call)
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])

    with pytest.raises(ToolError, match="'Layer 1' is locked; unlock it first"):
        await call(
            "move_region", path="a.aseprite", layer="Layer 1", rect=rect(0, 0, 2, 2), dx=1, dy=0
        )


async def test_copy_region_from_locked_layer_to_another_layer(call, locks, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="Top")
    await pixels(path, put=[(1, 1, *RED)])
    await locks(path, lock=["Layer 1"])

    await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(1, 1, 1, 1),
        dx=0,
        dy=0,
        copy=True,
        target_layer="Top",
    )

    assert await pixels(path, read=[(1, 1)], layer="Top") == [RED]


async def test_move_region_refuses_tilemap_layer(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="Tiles", kind="tilemap", tile_size=4)

    with pytest.raises(ToolError, match="'Tiles' is a tilemap layer"):
        await call(
            "move_region", path="a.aseprite", layer="Tiles", rect=rect(0, 0, 4, 4), dx=4, dy=0
        )


async def test_move_region_does_not_write_through_linked_cel(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await linked_frames(call, pixels, path)

    await call(
        "move_region",
        path="a.aseprite",
        layer="Layer 1",
        rect=rect(1, 1, 1, 1),
        dx=2,
        dy=0,
        frame=2,
    )

    assert await pixels(path, read=[(1, 1), (3, 1)], frame=1) == [RED, CLEAR]
    assert await pixels(path, read=[(1, 1), (3, 1)], frame=2) == [CLEAR, RED]
    assert await pixels(path, read=[(1, 1), (3, 1)], frame=3) == [RED, CLEAR]
    first, second, third = await cels(path)
    assert first["image_id"] == third["image_id"] != second["image_id"]


async def test_erase_region_clears_only_the_rect_in_each_frame(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    await pixels(path, put=[(1, 1, *RED), (2, 1, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3")

    result = await call(
        "erase_region", path="a.aseprite", layer="Layer 1", rect=rect(0, 0, 2, 2), frames="1-2"
    )

    assert result == {"layer": "Layer 1", "erased_frames": 2, "skipped_frames": 0}
    for frame in (1, 2):
        assert await pixels(path, read=[(1, 1), (2, 1)], frame=frame) == [CLEAR, RED]
    assert await pixels(path, read=[(1, 1)], frame=3) == [RED]


async def test_erase_region_skips_missing_cels(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    await pixels(path, put=[(1, 1, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3")
    await call("clear_cels", path="a.aseprite", layer="Layer 1", frames=2)

    result = await call(
        "erase_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 1, 1), frames="all"
    )

    assert (result["erased_frames"], result["skipped_frames"]) == (2, 1)
    assert await pixels(path, read=[(1, 1)], frame=3) == [CLEAR]


async def test_erase_region_on_linked_frame_keeps_other_frames(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await linked_frames(call, pixels, path)

    await call("erase_region", path="a.aseprite", layer="Layer 1", rect=rect(1, 1, 1, 1), frames=2)

    assert await pixels(path, read=[(1, 1)], frame=1) == [RED]
    assert await pixels(path, read=[(1, 1)], frame=2) == [CLEAR]


async def test_flip_layer_mirrors_around_canvas(call, pixels, grid, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 8, 2)
    await trimmed(call, pixels, path, (1, 0), (2, 0), (1, 1))
    assert await grid(path) == [
        ".##.....",
        ".#......",
    ]

    result = await call("flip", path="a.aseprite", axis="horizontal", layer="Layer 1")

    assert result == {"axis": "horizontal", "layers": 1, "frames": 1, "cels": 1}
    assert await grid(path) == [
        ".....##.",
        "......#.",
    ]
    assert (await cels(path))[0]["x"] == 5


async def test_flip_vertical(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await trimmed(call, pixels, path, (1, 0), (2, 0), (1, 1))

    await call("flip", path="a.aseprite", axis="vertical", layer="Layer 1")

    assert await grid(path) == [
        "....",
        "....",
        ".#..",
        ".##.",
    ]


async def test_flip_whole_sprite_flips_every_layer(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")
    await call("add_layer", path="a.aseprite", name="Ink", parent="G")
    await pixels(path, put=[(1, 0, *RED)])
    await pixels(path, put=[(0, 3, *BLUE)], layer="G/Ink")

    result = await call("flip", path="a.aseprite", axis="horizontal")

    assert result["layers"] == 2
    assert await pixels(path, read=[(1, 0), (6, 0)]) == [CLEAR, RED]
    assert await pixels(path, read=[(0, 3), (7, 3)], layer="G/Ink") == [CLEAR, BLUE]


async def test_flip_keeps_offcanvas_cel_content(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await trimmed(call, pixels, path, (-2, 0), (1, 0))

    await call("flip", path="a.aseprite", axis="horizontal", layer="Layer 1")

    assert await pixels(path, read=[(6, 0), (9, 0), (1, 0), (-2, 0)]) == [RED, RED, CLEAR, CLEAR]


async def test_flip_linked_cels_only_for_requested_frames(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await linked_frames(call, pixels, path)

    await call("flip", path="a.aseprite", axis="horizontal", layer="Layer 1", frames=2)

    assert await pixels(path, read=[(1, 1), (6, 1)], frame=1) == [RED, CLEAR]
    assert await pixels(path, read=[(1, 1), (6, 1)], frame=2) == [CLEAR, RED]
    assert await pixels(path, read=[(1, 1), (6, 1)], frame=3) == [RED, CLEAR]
    first, second, third = await cels(path)
    assert first["image_id"] == third["image_id"] != second["image_id"]


async def test_flip_linked_cels_once_when_all_their_frames_are_requested(
    call, pixels, cels, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await linked_frames(call, pixels, path)

    result = await call("flip", path="a.aseprite", axis="horizontal", layer="Layer 1")

    assert (result["frames"], result["cels"]) == (3, 1)
    for frame in (1, 2, 3):
        assert await pixels(path, read=[(6, 1)], frame=frame) == [RED]
    assert len({cel["image_id"] for cel in await cels(path)}) == 1


async def test_flip_indexed_keeps_indices(call, pixels, set_palette, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (10, 10, 10, 255), (255, 0, 0, 255)])
    await pixels(path, put=[(1, 1, *RED)])
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (255, 0, 0, 255)])

    await call("flip", path="a.aseprite", axis="horizontal")

    assert await pixels(path, read=[(1, 1), (6, 1)], values=True) == [0, 2]


async def test_flip_whole_sprite_ignores_locks(call, locks, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="G", kind="group")
    await call("update_layer", path="a.aseprite", layer="Layer 1", parent="G")
    await pixels(path, put=[(1, 0, *RED)], layer="G/Layer 1")
    await locks(path, lock=["G"])

    await call("flip", path="a.aseprite", axis="horizontal")

    assert await pixels(path, read=[(1, 0), (6, 0)], layer="G/Layer 1") == [CLEAR, RED]
    assert await locks(path) == ["G"]


async def test_flip_one_layer_refuses_locked_layer(call, locks, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(1, 0, *RED)])
    await locks(path, lock=["Layer 1"])
    before = path.read_bytes()

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call("flip", path="a.aseprite", axis="horizontal", layer="Layer 1")

    assert path.read_bytes() == before


async def test_rotate_whole_sprite_ignores_locks(call, locks, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call)
    await pixels(path, put=[(0, 0, *RED)])
    await locks(path, lock=["Layer 1"])

    await call("rotate", path="a.aseprite", angle=180)

    assert await pixels(path, read=[(0, 0), (7, 7)]) == [CLEAR, RED]


async def test_flip_whole_sprite_refuses_tilemap_layer(call):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="Tiles", kind="tilemap", tile_size=4)

    with pytest.raises(ToolError, match="'Tiles' is a tilemap layer"):
        await call("flip", path="a.aseprite", axis="vertical")


async def test_rotate_layer_90_around_canvas_centre(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await trimmed(call, pixels, path, (0, 0), (1, 0), (0, 1))
    assert await grid(path) == [
        "##..",
        "#...",
        "....",
        "....",
    ]

    result = await call("rotate", path="a.aseprite", angle=90, layer="Layer 1")

    assert result == {
        "angle": 90,
        "layers": 1,
        "frames": 1,
        "cels": 1,
        "width": 4,
        "height": 4,
    }
    assert await grid(path) == [
        "..##",
        "...#",
        "....",
        "....",
    ]


async def test_rotate_layer_180(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await trimmed(call, pixels, path, (0, 0), (1, 0), (0, 1))

    await call("rotate", path="a.aseprite", angle=180, layer="Layer 1")

    assert await grid(path) == [
        "....",
        "....",
        "...#",
        "..##",
    ]


async def test_rotate_layer_270(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await trimmed(call, pixels, path, (0, 0), (1, 0), (0, 1))

    await call("rotate", path="a.aseprite", angle=270, layer="Layer 1")

    assert await grid(path) == [
        "....",
        "....",
        "#...",
        "##..",
    ]


async def test_rotate_layer_non_square_canvas_keeps_canvas_size(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 6, 4)
    await trimmed(call, pixels, path, (0, 0), (2, 1), (3, 1))

    result = await call("rotate", path="a.aseprite", angle=90, layer="Layer 1")

    assert (result["width"], result["height"]) == (6, 4)
    assert await grid(path) == [
        "......",
        "...#..",
        "...#..",
        "......",
    ]
    assert await pixels(path, read=[(4, -1)]) == [RED]


async def test_rotate_layer_odd_size_difference_rounds_towards_top_left(
    call, pixels, grid, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 4)
    await trimmed(call, pixels, path, (2, 1), (3, 1))

    await call("rotate", path="a.aseprite", angle=90, layer="Layer 1")

    assert await grid(path) == [
        ".....",
        "..#..",
        "..#..",
        ".....",
    ]


async def test_rotate_layer_270_undoes_90_on_odd_size_difference(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 5, 4)
    await trimmed(call, pixels, path, (1, 1))

    await call("rotate", path="a.aseprite", angle=90, layer="Layer 1")
    assert await pixels(path, read=[(2, 0)]) == [RED]
    await call("rotate", path="a.aseprite", angle=270, layer="Layer 1")

    assert await pixels(path, read=[(1, 1), (0, 1)]) == [RED, CLEAR]


async def test_rotate_layer_turns_linked_cels_once(call, pixels, cels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await linked_frames(call, pixels, path)

    result = await call("rotate", path="a.aseprite", angle=90, layer="Layer 1")

    assert (result["frames"], result["cels"]) == (3, 1)
    for frame in (1, 2, 3):
        assert await pixels(path, read=[(6, 1), (1, 1)], frame=frame) == [RED, CLEAR]
    assert len({cel["image_id"] for cel in await cels(path)}) == 1


async def test_rotate_whole_sprite_swaps_canvas_size_and_rotates_all_layers(
    call, pixels, grid, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 2)
    await call("add_frames", path="a.aseprite", count=1)
    await call("add_layer", path="a.aseprite", name="Top")
    await pixels(path, put=[(0, 0, *RED)])
    await pixels(path, put=[(3, 1, *BLUE)], layer="Top", frame=2)

    result = await call("rotate", path="a.aseprite", angle=90)

    assert (result["width"], result["height"], result["frames"]) == (2, 4, 2)
    info = await call("get_sprite_info", path="a.aseprite")
    assert (info["width"], info["height"]) == (2, 4)
    assert await grid(path) == [".#", "..", "..", ".."]
    assert await grid(path, layer="Top", frame=2) == ["..", "..", "..", "#."]


async def test_rotate_whole_sprite_270_turns_anticlockwise(call, pixels, grid, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 2)
    await pixels(path, put=[(0, 0, *RED)])

    await call("rotate", path="a.aseprite", angle=270)

    assert await grid(path) == ["..", "..", "..", "#."]


async def test_rotate_whole_sprite_needs_all_frames(call):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)

    with pytest.raises(ToolError, match="whole sprite"):
        await call("rotate", path="a.aseprite", angle=90, frames=1)


async def test_rotate_all_frames(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await call("add_frames", path="a.aseprite", count=2)
    await pixels(path, put=[(0, 0, *RED)])
    await call("copy_frames", path="a.aseprite", source=1, targets="2-3")

    result = await call("rotate", path="a.aseprite", angle=180, layer="Layer 1", frames="all")

    assert (result["frames"], result["cels"]) == (3, 3)
    for frame in (1, 2, 3):
        assert await pixels(path, read=[(0, 0), (3, 3)], frame=frame) == [CLEAR, RED]


async def test_region_tools_in_one_batch(call, pixels, tmp_path: Path, monkeypatch):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4)
    await pixels(path, put=[(0, 0, *RED), (3, 3, *BLUE)])
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
            {
                "tool": "move_region",
                "args": {"layer": "Layer 1", "rect": rect(0, 0, 1, 1), "dx": 1, "dy": 0},
            },
            {"tool": "erase_region", "args": {"layer": "Layer 1", "rect": rect(3, 3, 1, 1)}},
            {"tool": "flip", "args": {"axis": "vertical"}},
            {"tool": "rotate", "args": {"angle": 90}},
        ],
    )

    assert len(calls) == 1
    assert [r["cels"] for r in result["result"][2:]] == [1, 1]
    assert await pixels(path, read=[(0, 1), (1, 0), (3, 3)]) == [RED, CLEAR, CLEAR]


async def test_copy_region_onto_background_keeps_it_opaque(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4, background="#ffffff")
    await pixels(path, background=True)
    await call("add_layer", path="a.aseprite", name="Top")
    await pixels(path, put=[(0, 0, *RED)], layer="Top")

    await call(
        "move_region",
        path="a.aseprite",
        layer="Top",
        rect=rect(0, 0, 2, 2),
        dx=2,
        dy=2,
        copy=True,
        target_layer="Background",
    )

    assert await pixels(path, read=[(2, 2), (3, 2), (2, 3), (3, 3)], layer="Background") == [
        RED,
        WHITE,
        WHITE,
        WHITE,
    ]


async def test_move_region_inside_background_leaves_opaque_black(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4, background="#ffffff")
    await pixels(path, put=[(0, 0, *RED)], background=True)

    await call(
        "move_region", path="a.aseprite", layer="Background", rect=rect(0, 0, 1, 1), dx=1, dy=0
    )

    assert await pixels(path, read=[(0, 0), (1, 0)], layer="Background") == [
        [0, 0, 0, 255],
        RED,
    ]


async def test_move_region_on_indexed_background_copies_raw_indices(
    call, pixels, set_palette, tmp_path: Path
):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4, color_mode="indexed")
    await set_palette(path, [(0, 0, 0, 0), (255, 0, 0, 255), (255, 255, 255, 255)])
    await pixels(path, put=[(0, 0, 0, 0, 0, 255), (1, 0, 255, 255, 255, 255)], background=True)

    await call(
        "move_region", path="a.aseprite", layer="Background", rect=rect(0, 0, 1, 1), dx=1, dy=0
    )

    assert await pixels(path, read=[(1, 0)], layer="Background", values=True) == [0]


async def test_erase_region_on_background_paints_opaque_black(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await new_sprite(call, 4, 4, background="#ffffff")
    await pixels(path, background=True)

    await call("erase_region", path="a.aseprite", layer="Background", rect=rect(0, 0, 2, 1))

    assert await pixels(path, read=[(0, 0), (1, 0), (2, 0)], layer="Background") == [
        [0, 0, 0, 255],
        [0, 0, 0, 255],
        WHITE,
    ]


async def test_many_moves_in_one_batch_on_a_large_sprite(call, pixels, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=1024, height=1024, background="#ffffff")
    ops = [
        {
            "tool": "move_region",
            "args": {"layer": "Layer 1", "rect": rect(i, 0, 1, 1), "dx": 0, "dy": 1},
        }
        for i in range(100)
    ]

    await call("batch", path="a.aseprite", ops=ops)

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (99, 0), (100, 0), (0, 1)]) == [
        CLEAR,
        CLEAR,
        WHITE,
        WHITE,
    ]
