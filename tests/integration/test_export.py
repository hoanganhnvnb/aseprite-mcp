import dataclasses
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from aseprite_mcp import server
from aseprite_mcp.errors import ToolError

RED = "#ff0000"
GREEN = "#00ff00"
BLUE = "#0000ff"


async def new_sprite(call, w: int = 4, h: int = 3, name: str = "a.aseprite", **args) -> None:
    await call("create_sprite", path=name, width=w, height=h, **args)


async def put(call, *pixels: tuple[int, int, str], name: str = "a.aseprite", **args) -> None:
    await call(
        "draw_pixels",
        path=name,
        pixels=[{"x": x, "y": y, "color": c} for x, y, c in pixels],
        **args,
    )


def rgba(path: Path, xy: tuple[int, int]) -> tuple[int, int, int, int]:
    with Image.open(path) as img:
        return img.convert("RGBA").getpixel(xy)


def size(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def use_sandbox(ase_settings, monkeypatch) -> None:
    sandboxed = dataclasses.replace(ase_settings, sandbox=True)
    monkeypatch.setattr(server, "get_settings", lambda: sandboxed)


async def test_export_png_single_frame(call, tmp_path):
    await new_sprite(call)
    await put(call, (0, 0, RED))

    result = await call("export", path="a.aseprite", output="a.png")

    assert result["files"] == [str(tmp_path / "a.png")]
    assert result["frames"] == [1]
    assert (result["width"], result["height"]) == (4, 3)
    assert rgba(tmp_path / "a.png", (0, 0)) == (255, 0, 0, 255)
    assert rgba(tmp_path / "a.png", (1, 0)) == (0, 0, 0, 0)


async def test_export_does_not_touch_unrelated_files(call, tmp_path):
    await new_sprite(call, name="hero.aseprite")
    await call("add_frames", path="hero.aseprite", count=2)
    (tmp_path / "hero_walk.png").write_bytes(b"not really a png")
    (tmp_path / "hero1.png").write_bytes(b"also kept")

    await call("export", path="hero.aseprite", output="hero.png", frames="1")

    assert (tmp_path / "hero_walk.png").read_bytes() == b"not really a png"
    assert (tmp_path / "hero1.png").read_bytes() == b"also kept"
    assert names(tmp_path) == ["hero.aseprite", "hero.png", "hero1.png", "hero_walk.png"]


async def test_export_refuses_existing_output(call, tmp_path):
    await new_sprite(call)
    (tmp_path / "a.png").write_bytes(b"old")

    with pytest.raises(ToolError, match="already exists; pass overwrite=true"):
        await call("export", path="a.aseprite", output="a.png")

    assert (tmp_path / "a.png").read_bytes() == b"old"


async def test_export_overwrite_replaces_output(call, tmp_path):
    await new_sprite(call)
    (tmp_path / "a.png").write_bytes(b"old")

    await call("export", path="a.aseprite", output="a.png", overwrite=True)

    assert size(tmp_path / "a.png") == (4, 3)


async def test_export_unknown_extension_lists_allowed(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match=r"\('.jpg'\); use one of: bmp, gif, png, qoi, tga, webp"):
        await call("export", path="a.aseprite", output="a.jpg")


async def test_export_several_frames_to_png_numbers_the_files(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)

    result = await call("export", path="a.aseprite", output="walk.png", frames="1-3")

    assert result["files"] == [str(tmp_path / f"walk_{n}.png") for n in (1, 2, 3)]
    assert names(tmp_path) == ["a.aseprite", "walk_1.png", "walk_2.png", "walk_3.png"]


async def test_export_numbers_files_by_frame_number(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=3)

    result = await call("export", path="a.aseprite", output="walk.png", frames="2,4")

    assert result["files"] == [str(tmp_path / "walk_2.png"), str(tmp_path / "walk_4.png")]


async def test_export_png_without_frames_takes_frame_one(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await put(call, (1, 1, RED), frame=2)

    result = await call("export", path="a.aseprite", output="a.png")

    assert result["files"] == [str(tmp_path / "a.png")]
    assert rgba(tmp_path / "a.png", (1, 1)) == (0, 0, 0, 0)


async def test_export_tag_exports_its_frames(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=3)
    await call("set_tag", path="a.aseprite", name="walk", from_frame=2, to_frame=3)

    result = await call("export", path="a.aseprite", output="w.png", tag="walk")

    assert result["frames"] == [2, 3]
    assert result["files"] == [str(tmp_path / "w_2.png"), str(tmp_path / "w_3.png")]


async def test_export_unknown_tag(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="tag 'run' not found"):
        await call("export", path="a.aseprite", output="w.gif", tag="run")


async def test_export_refuses_frames_and_tag_together(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="frames or tag, not both"):
        await call("export", path="a.aseprite", output="w.png", frames="1", tag="walk")


async def test_export_frame_out_of_range(call, tmp_path):
    await new_sprite(call)

    with pytest.raises(ToolError, match="frame 2 is out of range"):
        await call("export", path="a.aseprite", output="a.png", frames="2")

    assert names(tmp_path) == ["a.aseprite"]


async def test_export_gif_keeps_frames_and_durations(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1, duration_ms=250)
    await put(call, (0, 0, RED))
    await put(call, (1, 0, BLUE), frame=2)

    result = await call("export", path="a.aseprite", output="a.gif")

    assert result["files"] == [str(tmp_path / "a.gif")]
    assert result["frames"] == [1, 2]
    with Image.open(tmp_path / "a.gif") as img:
        assert img.n_frames == 2
        durations = []
        for i in range(2):
            img.seek(i)
            durations.append(img.info["duration"])
        assert img.info["loop"] == 0
    assert durations == [100, 250]


async def test_export_gif_scaled_size(call, tmp_path):
    await new_sprite(call, w=3, h=2)
    await call("add_frames", path="a.aseprite", count=1)

    await call("export", path="a.aseprite", output="a.gif", scale=4)

    with Image.open(tmp_path / "a.gif") as img:
        assert img.size == (12, 8)
        assert img.n_frames == 2


async def test_export_webp_animation(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await put(call, (0, 0, RED))
    await put(call, (1, 0, BLUE), frame=2)

    await call("export", path="a.aseprite", output="a.webp")

    with Image.open(tmp_path / "a.webp") as img:
        assert img.n_frames == 2


async def test_export_png_scale_is_nearest_neighbour(call, tmp_path):
    await new_sprite(call)
    await put(call, (0, 0, RED))

    result = await call("export", path="a.aseprite", output="a.png", scale=3)

    assert (result["width"], result["height"]) == (12, 9)
    assert rgba(tmp_path / "a.png", (2, 2)) == (255, 0, 0, 255)
    assert rgba(tmp_path / "a.png", (3, 3)) == (0, 0, 0, 0)


async def test_export_refuses_huge_output(call):
    await new_sprite(call, w=1024, h=1024)

    with pytest.raises(ToolError, match="too large"):
        await call("export", path="a.aseprite", output="a.png", scale=32)


async def test_export_one_layer(call, tmp_path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="top")
    await put(call, (0, 0, RED))
    await put(call, (1, 0, BLUE), layer="top")

    await call("export", path="a.aseprite", output="a.png", layer="top")

    assert rgba(tmp_path / "a.png", (0, 0)) == (0, 0, 0, 0)
    assert rgba(tmp_path / "a.png", (1, 0)) == (0, 0, 255, 255)


async def test_export_one_group_composites_its_layers(call, tmp_path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="g", kind="group")
    await call("add_layer", path="a.aseprite", name="arm", parent="g")
    await put(call, (0, 0, RED))
    await put(call, (1, 0, BLUE), layer="g/arm")

    await call("export", path="a.aseprite", output="a.png", layer="g")

    assert rgba(tmp_path / "a.png", (0, 0)) == (0, 0, 0, 0)
    assert rgba(tmp_path / "a.png", (1, 0)) == (0, 0, 255, 255)


async def test_export_leaves_out_hidden_layers(call, tmp_path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="top")
    await put(call, (0, 0, RED), layer="top")
    await call("update_layer", path="a.aseprite", layer="top", visible=False)

    await call("export", path="a.aseprite", output="a.png")

    assert rgba(tmp_path / "a.png", (0, 0)) == (0, 0, 0, 0)


async def test_export_background_fills_transparent_pixels(call, tmp_path):
    await new_sprite(call)
    await put(call, (0, 0, RED))

    await call("export", path="a.aseprite", output="a.png", background=GREEN)

    assert rgba(tmp_path / "a.png", (0, 0)) == (255, 0, 0, 255)
    assert rgba(tmp_path / "a.png", (2, 2)) == (0, 255, 0, 255)


async def test_export_indexed_sprite(call, tmp_path):
    await new_sprite(call, color_mode="indexed")
    await put(call, (0, 0, "#ffffff"))

    await call("export", path="a.aseprite", output="a.png")

    assert rgba(tmp_path / "a.png", (0, 0)) == (255, 255, 255, 255)
    assert rgba(tmp_path / "a.png", (1, 0)) == (0, 0, 0, 0)


async def test_export_leaves_sprite_file_untouched(call, tmp_path):
    await new_sprite(call)
    await put(call, (0, 0, RED))
    sprite = tmp_path / "a.aseprite"
    before = sprite.read_bytes(), sprite.stat().st_mtime_ns, sprite.stat().st_ino

    await call("export", path="a.aseprite", output="a.gif", scale=2, background=GREEN)

    after = sprite.read_bytes(), sprite.stat().st_mtime_ns, sprite.stat().st_ino
    assert after == before


async def test_export_refuses_the_sprite_itself_as_output(call, tmp_path):
    await new_sprite(call, name="a.png")

    with pytest.raises(ToolError, match="different file than the sprite"):
        await call("export", path="a.png", output="a.png", overwrite=True)


async def test_export_refuses_output_outside_sandbox(call, ase_settings, monkeypatch, tmp_path):
    await new_sprite(call)
    use_sandbox(ase_settings, monkeypatch)

    with pytest.raises(ToolError, match="outside the allowed root"):
        await call("export", path="a.aseprite", output="../escaped.png")

    assert not (tmp_path.parent / "escaped.png").exists()


async def test_export_needs_existing_folder(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="Folder does not exist"):
        await call("export", path="a.aseprite", output="missing/a.png")


async def test_export_checks_every_numbered_file_before_writing(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    (tmp_path / "w_2.png").write_bytes(b"old")

    with pytest.raises(ToolError, match="w_2.png already exists"):
        await call("export", path="a.aseprite", output="w.png", frames="1-2")

    assert names(tmp_path) == ["a.aseprite", "w_2.png"]


async def test_failed_export_removes_the_files_it_wrote(call, tmp_path, monkeypatch):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    real_replace = os.replace
    moves = []

    def failing_replace(src, dst):
        moves.append(dst)
        if len(moves) == 2:
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(ToolError, match="disk full"):
        await call("export", path="a.aseprite", output="w.png", frames="all")

    assert names(tmp_path) == ["a.aseprite"]


async def test_export_is_not_batchable(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="'export' cannot be used in batch"):
        await call(
            "batch", path="a.aseprite", ops=[{"tool": "export", "args": {"output": "a.png"}}]
        )


async def test_spritesheet_horizontal_size(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)

    result = await call("export_spritesheet", path="a.aseprite", output="sheet.png")

    assert result["files"] == [str(tmp_path / "sheet.png")]
    assert (result["width"], result["height"]) == (12, 3)
    assert size(tmp_path / "sheet.png") == (12, 3)


async def test_spritesheet_vertical_size(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)

    await call("export_spritesheet", path="a.aseprite", output="sheet.png", sheet_type="vertical")

    assert size(tmp_path / "sheet.png") == (4, 9)


async def test_spritesheet_json_valid(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)

    result = await call(
        "export_spritesheet", path="a.aseprite", output="sheet.png", data_output="sheet.json"
    )

    assert result["files"] == [str(tmp_path / "sheet.png"), str(tmp_path / "sheet.json")]
    data = json.loads((tmp_path / "sheet.json").read_text(encoding="utf-8"))
    assert isinstance(data["frames"], dict)
    assert len(data["frames"]) == 3
    assert data["meta"]["image"] == "sheet.png"
    assert data["meta"]["size"] == {"w": 12, "h": 3}


async def test_spritesheet_array_data(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)

    await call(
        "export_spritesheet",
        path="a.aseprite",
        output="sheet.png",
        data_output="sheet.json",
        data_format="array",
    )

    data = json.loads((tmp_path / "sheet.json").read_text(encoding="utf-8"))
    assert [f["frame"] for f in data["frames"]] == [
        {"x": 0, "y": 0, "w": 4, "h": 3},
        {"x": 4, "y": 0, "w": 4, "h": 3},
    ]


async def test_spritesheet_data_in_another_folder_points_at_the_image(call, tmp_path):
    await new_sprite(call)
    (tmp_path / "data").mkdir()

    await call(
        "export_spritesheet", path="a.aseprite", output="sheet.png", data_output="data/s.json"
    )

    data = json.loads((tmp_path / "data" / "s.json").read_text(encoding="utf-8"))
    assert data["meta"]["image"] == "../sheet.png"


async def test_spritesheet_tag_with_padding(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=3)
    await call("set_tag", path="a.aseprite", name="walk", from_frame=2, to_frame=3)

    result = await call(
        "export_spritesheet", path="a.aseprite", output="sheet.png", tag="walk", padding=2
    )

    assert result["frame_count"] == 2
    assert size(tmp_path / "sheet.png") == (10, 3)


async def test_spritesheet_scale(call, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    await put(call, (0, 0, RED))

    await call("export_spritesheet", path="a.aseprite", output="sheet.png", scale=2)

    assert size(tmp_path / "sheet.png") == (16, 6)
    assert rgba(tmp_path / "sheet.png", (1, 1)) == (255, 0, 0, 255)


async def test_spritesheet_refuses_existing_data_file(call, tmp_path):
    await new_sprite(call)
    (tmp_path / "sheet.json").write_text("{}")

    with pytest.raises(ToolError, match="sheet.json already exists"):
        await call(
            "export_spritesheet", path="a.aseprite", output="sheet.png", data_output="sheet.json"
        )

    assert names(tmp_path) == ["a.aseprite", "sheet.json"]


async def test_spritesheet_data_must_be_json(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="must be a .json file"):
        await call(
            "export_spritesheet", path="a.aseprite", output="sheet.png", data_output="sheet.txt"
        )


async def test_spritesheet_image_must_not_be_animated(call):
    await new_sprite(call)

    with pytest.raises(ToolError, match="use one of: bmp, png, qoi, tga"):
        await call("export_spritesheet", path="a.aseprite", output="sheet.gif")


async def test_export_layers_writes_one_png_per_layer(call, tmp_path):
    await new_sprite(call)
    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name="body")
    await call("add_layer", path="a.aseprite", name="hat")
    await put(call, (0, 0, RED), layer="body")
    await put(call, (1, 0, BLUE), layer="hat")

    result = await call("export_layers", path="a.aseprite", output_dir="parts")

    parts = tmp_path / "parts"
    assert result["files"] == [
        {"layer": "body", "file": str(parts / "body.png")},
        {"layer": "hat", "file": str(parts / "hat.png")},
    ]
    assert rgba(parts / "body.png", (0, 0)) == (255, 0, 0, 255)
    assert rgba(parts / "body.png", (1, 0)) == (0, 0, 0, 0)
    assert rgba(parts / "hat.png", (1, 0)) == (0, 0, 255, 255)


async def test_export_layers_skips_hidden_layers(call, tmp_path):
    await new_sprite(call)
    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name="body")
    await call("add_layer", path="a.aseprite", name="ghost")
    await call("update_layer", path="a.aseprite", layer="ghost", visible=False)

    result = await call("export_layers", path="a.aseprite", output_dir=".")

    assert [f["layer"] for f in result["files"]] == ["body"]
    assert result["hidden"] == ["ghost"]
    assert not (tmp_path / "ghost.png").exists()


async def test_export_layers_can_include_hidden_layers(call, tmp_path):
    await new_sprite(call)
    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name="body")
    await call("add_layer", path="a.aseprite", name="ghost")
    await put(call, (0, 0, RED), layer="ghost")
    await call("update_layer", path="a.aseprite", layer="ghost", visible=False)

    await call("export_layers", path="a.aseprite", output_dir=".", include_hidden=True)

    assert rgba(tmp_path / "ghost.png", (0, 0)) == (255, 0, 0, 255)


async def test_export_layers_names_nested_layers_by_path(call, tmp_path):
    await new_sprite(call)
    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name="body")
    await call("add_layer", path="a.aseprite", name="arms", kind="group")
    await call("add_layer", path="a.aseprite", name="left", parent="arms")
    await put(call, (2, 0, GREEN), layer="arms/left")

    result = await call("export_layers", path="a.aseprite", output_dir="out")

    assert [(f["layer"], Path(f["file"]).name) for f in result["files"]] == [
        ("body", "body.png"),
        ("arms/left", "arms_left.png"),
    ]
    assert rgba(tmp_path / "out" / "arms_left.png", (2, 0)) == (0, 255, 0, 255)


async def test_export_layers_sanitizes_names(call, tmp_path):
    await new_sprite(call)
    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name='a<b>:"c"|?*')
    await call("add_layer", path="a.aseprite", name="a/b")
    await call("add_layer", path="a.aseprite", name="a_b")
    await call("add_layer", path="a.aseprite", name="CON")

    result = await call("export_layers", path="a.aseprite", output_dir="out")

    assert [Path(f["file"]).name for f in result["files"]] == [
        "a_b___c____.png",
        "a_b.png",
        "a_b_2.png",
        "_CON.png",
    ]
    assert names(tmp_path / "out") == ["_CON.png", "a_b.png", "a_b_2.png", "a_b___c____.png"]


async def test_export_layers_refuses_existing_file(call, tmp_path):
    await new_sprite(call)
    await call("update_layer", path="a.aseprite", layer="Layer 1", new_name="body")
    (tmp_path / "body.png").write_bytes(b"old")

    with pytest.raises(ToolError, match="body.png already exists"):
        await call("export_layers", path="a.aseprite", output_dir=".")

    assert (tmp_path / "body.png").read_bytes() == b"old"


async def test_export_layers_output_dir_must_not_be_a_file(call, tmp_path):
    await new_sprite(call)
    (tmp_path / "parts").write_text("")

    with pytest.raises(ToolError, match="is not a folder"):
        await call("export_layers", path="a.aseprite", output_dir="parts")


def write_png(path: Path, pixels: dict[tuple[int, int], tuple], w: int = 2, h: int = 2) -> None:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for xy, color in pixels.items():
        img.putpixel(xy, color)
    img.save(path)


async def test_import_image_draws_its_pixels(call, pixels, tmp_path):
    await new_sprite(call)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255), (1, 1): (0, 0, 255, 255)})

    result = await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")

    assert result == {
        "layer": "Layer 1",
        "frame": 1,
        "x": 0,
        "y": 0,
        "width": 2,
        "height": 2,
        "placed": 2,
        "clipped": 0,
    }
    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 1), (1, 0)]) == [
        [255, 0, 0, 255],
        [0, 0, 255, 255],
        [0, 0, 0, 0],
    ]


async def test_import_image_at_an_offset(call, pixels, tmp_path):
    await new_sprite(call)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255)})

    await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1", x=2, y=1)

    assert await pixels(tmp_path / "a.aseprite", read=[(2, 1), (0, 0)]) == [
        [255, 0, 0, 255],
        [0, 0, 0, 0],
    ]


async def test_import_image_clips_to_the_canvas(call, tmp_path):
    await new_sprite(call)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255), (1, 0): (0, 0, 255, 255)})

    result = await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1", x=3)

    assert (result["placed"], result["clipped"]) == (1, 1)


async def test_import_image_entirely_off_canvas(call, tmp_path):
    await new_sprite(call)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255)})

    with pytest.raises(ToolError, match="outside the canvas"):
        await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1", x=10)


async def test_import_image_keeps_pixels_under_transparent_ones(call, pixels, tmp_path):
    await new_sprite(call)
    await put(call, (1, 1, GREEN))
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255)})

    await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")

    assert await pixels(tmp_path / "a.aseprite", read=[(1, 1)]) == [[0, 255, 0, 255]]


async def test_import_image_grows_the_cel(call, images, tmp_path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="top")
    await put(call, (0, 0, RED), layer="top")
    write_png(tmp_path / "in.png", {(0, 0): (0, 0, 255, 255)}, w=1, h=1)

    await call("import_image", path="a.aseprite", image="in.png", layer="top", x=3, y=2)

    [cel] = await images(tmp_path / "a.aseprite", layer="top")
    assert cel.split(":")[0] == "0,0,4,3"


async def test_import_image_into_new_frame_cel(call, pixels, tmp_path):
    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=1)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255)})

    await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1", frame=2)

    path = tmp_path / "a.aseprite"
    assert await pixels(path, read=[(0, 0)], frame=2) == [[255, 0, 0, 255]]
    assert await pixels(path, read=[(0, 0)], frame=1) == [[0, 0, 0, 0]]


async def test_import_image_refuses_locked_layer(call, locks, tmp_path):
    await new_sprite(call)
    await locks(tmp_path / "a.aseprite", lock=["Layer 1"])
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255)})

    with pytest.raises(ToolError, match="'Layer 1' is locked"):
        await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")


async def test_import_image_refuses_group(call, tmp_path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="g", kind="group")
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255)})

    with pytest.raises(ToolError, match="'g' is a group"):
        await call("import_image", path="a.aseprite", image="in.png", layer="g")


async def test_import_image_on_indexed_sprite_uses_palette(call, pixels, set_palette, tmp_path):
    await new_sprite(call, color_mode="indexed")
    path = tmp_path / "a.aseprite"
    await set_palette(path, [(0, 0, 0, 0), (250, 0, 0, 255), (0, 0, 250, 255)])
    write_png(tmp_path / "in.png", {(0, 0): (255, 10, 10, 255), (1, 0): (0, 0, 255, 255)})

    await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")

    assert await pixels(path, read=[(0, 0), (1, 0), (0, 1)], values=True) == [1, 2, 0]


async def test_import_image_takes_first_gif_frame(call, pixels, tmp_path):
    await new_sprite(call)
    first = Image.new("RGB", (2, 2), (255, 0, 0))
    second = Image.new("RGB", (2, 2), (0, 0, 255))
    first.save(tmp_path / "in.gif", save_all=True, append_images=[second])

    await call("import_image", path="a.aseprite", image="in.gif", layer="Layer 1")

    assert await pixels(tmp_path / "a.aseprite", read=[(1, 1)]) == [[255, 0, 0, 255]]


async def test_import_image_not_an_image(call, tmp_path):
    await new_sprite(call)
    (tmp_path / "notes.png").write_text("hello")

    with pytest.raises(ToolError, match="is not an image"):
        await call("import_image", path="a.aseprite", image="notes.png", layer="Layer 1")


async def test_import_image_too_large(call, tmp_path):
    await new_sprite(call)
    Image.new("RGBA", (4097, 1)).save(tmp_path / "wide.png")

    with pytest.raises(ToolError, match="is 4097x1, larger than 4096x4096"):
        await call("import_image", path="a.aseprite", image="wide.png", layer="Layer 1")


async def test_import_image_outside_sandbox(call, ase_settings, monkeypatch, tmp_path):
    await new_sprite(call)
    use_sandbox(ase_settings, monkeypatch)

    with pytest.raises(ToolError, match="outside the allowed root"):
        await call("import_image", path="a.aseprite", image="../in.png", layer="Layer 1")


async def test_export_path_with_spaces_and_unicode(call, tmp_path):
    await new_sprite(call, name="hé ro.aseprite")
    (tmp_path / "my exports").mkdir()

    result = await call("export", path="hé ro.aseprite", output="my exports/hé ro.png")

    assert result["files"] == [str(tmp_path / "my exports" / "hé ro.png")]
    assert size(tmp_path / "my exports" / "hé ro.png") == (4, 3)


async def test_spritesheet_leaves_out_hidden_layers(call, tmp_path):
    await new_sprite(call)
    await call("add_layer", path="a.aseprite", name="ghost")
    await put(call, (0, 0, RED), layer="ghost")
    await call("update_layer", path="a.aseprite", layer="ghost", visible=False)

    await call("export_spritesheet", path="a.aseprite", output="sheet.png")

    assert rgba(tmp_path / "sheet.png", (0, 0)) == (0, 0, 0, 0)


async def test_export_caps_total_pixels_of_numbered_files(call, monkeypatch, tmp_path):
    from aseprite_mcp.tools import export

    await new_sprite(call)
    await call("add_frames", path="a.aseprite", count=2)
    monkeypatch.setattr(export, "MAX_EXPORT_PIXELS", 30)

    await call("export", path="a.aseprite", output="one.png", frames="1")
    with pytest.raises(ToolError, match="3 frame\\(s\\) of 4x3 px, too large"):
        await call("export", path="a.aseprite", output="w.png", frames="all")

    assert names(tmp_path) == ["a.aseprite", "one.png"]


async def test_failed_export_layers_removes_the_folder_it_made(call, tmp_path, monkeypatch):
    await new_sprite(call)

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(ToolError, match="disk full"):
        await call("export_layers", path="a.aseprite", output_dir="new/parts")

    assert names(tmp_path) == ["a.aseprite"]


async def test_failed_export_layers_keeps_an_existing_folder(call, tmp_path, monkeypatch):
    await new_sprite(call)
    (tmp_path / "parts").mkdir()

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(ToolError, match="disk full"):
        await call("export_layers", path="a.aseprite", output_dir="parts")

    assert (tmp_path / "parts").is_dir()


async def test_import_image_on_grayscale_sprite_uses_luma(call, pixels, tmp_path):
    await new_sprite(call, color_mode="grayscale")
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255), (1, 0): (255, 255, 255, 128)})

    await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (1, 0), (0, 1)]) == [
        [54, 54, 54, 255],
        [255, 255, 255, 128],
        [0, 0, 0, 0],
    ]


async def test_import_image_on_indexed_background_keeps_index_zero(
    call, pixels, set_palette, tmp_path
):
    await new_sprite(call, color_mode="indexed")
    path = tmp_path / "a.aseprite"
    await set_palette(path, [(0, 0, 0, 255), (250, 0, 0, 255), (0, 0, 250, 255)])
    await pixels(path, put=[(1, 1, 0, 0, 250, 255)], background=True)
    write_png(tmp_path / "in.png", {(0, 0): (5, 5, 5, 255)})

    await call("import_image", path="a.aseprite", image="in.png", layer="Background")

    assert await pixels(path, read=[(0, 0), (1, 1)], layer="Background", values=True) == [0, 2]


async def test_import_image_with_too_many_colours_for_indexed(call, monkeypatch, tmp_path):
    from aseprite_mcp.tools import export

    await new_sprite(call, color_mode="indexed")
    monkeypatch.setattr(export, "MAX_PALETTE_WORK", 50)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255), (1, 0): (0, 0, 255, 255)})

    with pytest.raises(ToolError, match="the image has 3 colours; .* too much work"):
        await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")


async def test_import_image_counts_colours_in_python_past_the_limit(call, monkeypatch, tmp_path):
    from aseprite_mcp.tools import export

    await new_sprite(call, color_mode="indexed")
    monkeypatch.setattr(export, "MAX_COUNTED_COLORS", 2)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255), (1, 0): (0, 0, 255, 255)})

    with pytest.raises(ToolError, match="the image has too many colours"):
        await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")


async def test_import_image_into_rgb_sprite_has_no_colour_limit(call, monkeypatch, tmp_path):
    from aseprite_mcp.tools import export

    await new_sprite(call)
    monkeypatch.setattr(export, "MAX_PALETTE_WORK", 1)
    write_png(tmp_path / "in.png", {(0, 0): (255, 0, 0, 255), (1, 0): (0, 0, 255, 255)})

    result = await call("import_image", path="a.aseprite", image="in.png", layer="Layer 1")

    assert result["placed"] == 2
