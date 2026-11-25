from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from aseprite_mcp import ops, server
from aseprite_mcp.config import load_settings
from aseprite_mcp.errors import ToolError

RED = [255, 0, 0, 255]
CLEAR = [0, 0, 0, 0]


async def test_create_sprite_unicode_path(call, tmp_path: Path):
    folder = tmp_path / "my sprites" / "été ☃"
    folder.mkdir(parents=True)

    info = await call("create_sprite", path="my sprites/été ☃/hé llo.aseprite", width=24, height=10)

    assert (folder / "hé llo.aseprite").is_file()
    assert (info["width"], info["height"], info["color_mode"]) == (24, 10, "rgb")
    assert info["path"] == str(folder / "hé llo.aseprite")


async def test_create_refuses_overwrite(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    before = (tmp_path / "a.aseprite").read_bytes()

    with pytest.raises(ToolError, match="already exists"):
        await call("create_sprite", path="a.aseprite", width=16, height=16)

    assert (tmp_path / "a.aseprite").read_bytes() == before


async def test_create_overwrites_when_asked(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    info = await call("create_sprite", path="a.aseprite", width=16, height=4, overwrite=True)

    assert (info["width"], info["height"]) == (16, 4)


async def test_create_sprite_rejects_zero_width(call, tmp_path: Path):
    with pytest.raises(ToolError, match="width"):
        await call("create_sprite", path="a.aseprite", width=0, height=8)

    assert list(tmp_path.iterdir()) == []


async def test_create_sprite_needs_existing_folder(call):
    with pytest.raises(ToolError, match="Folder does not exist"):
        await call("create_sprite", path="missing/a.aseprite", width=8, height=8)


async def test_create_sprite_rejects_unknown_extension(call, tmp_path: Path):
    with pytest.raises(ToolError, match=r"cannot save a\.xyz \('\.xyz'\)"):
        await call("create_sprite", path="a.xyz", width=8, height=8)

    assert list(tmp_path.iterdir()) == []


async def test_create_sprite_needs_an_extension(call, tmp_path: Path):
    with pytest.raises(ToolError, match="no extension"):
        await call("create_sprite", path="sprite", width=8, height=8)

    assert list(tmp_path.iterdir()) == []


async def test_create_sprite_rejects_bad_background(call):
    with pytest.raises(ToolError, match="#RRGGBB"):
        await call("create_sprite", path="a.aseprite", width=8, height=8, background="red")


async def test_create_sprite_fills_background(call, pixels, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=4, height=4, background="#ff0000")

    assert await pixels(tmp_path / "a.aseprite", read=[(0, 0), (3, 3)]) == [RED, RED]


async def test_sprite_info_after_create(call):
    await call("create_sprite", path="a.aseprite", width=8, height=6, color_mode="grayscale")

    info = await call("get_sprite_info", path="a.aseprite")

    assert (info["width"], info["height"], info["color_mode"]) == (8, 6, "grayscale")
    assert info["frames"] == [{"index": 1, "duration_ms": 100}]
    assert [layer["name"] for layer in info["layers"]] == ["Layer 1"]


async def test_sprite_info_missing_file(call):
    with pytest.raises(ToolError, match="File not found"):
        await call("get_sprite_info", path="nope.aseprite")


async def test_set_color_mode_to_indexed(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4)
    await pixels(path, put=[(1, 1, 0, 0, 0, 255), (2, 2, 172, 50, 50, 255)])

    await call("set_color_mode", path="a.aseprite", mode="indexed")

    info = await call("get_sprite_info", path="a.aseprite")
    assert info["color_mode"] == "indexed"
    assert await pixels(path, read=[(1, 1), (2, 2), (0, 0)]) == [
        [0, 0, 0, 255],
        [172, 50, 50, 255],
        CLEAR,
    ]


async def test_gray_to_indexed_keeps_black(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4, color_mode="grayscale")
    await pixels(path, put=[(1, 1, 0, 0, 0, 255), (2, 2, 255, 255, 255, 255)])
    assert (await call("get_sprite_info", path="a.aseprite"))["palette_size"] == 256

    result = await call("set_color_mode", path="a.aseprite", mode="indexed")

    assert len(result["dropped_palette_entries"]) == 1
    assert (await call("get_sprite_info", path="a.aseprite"))["palette_size"] == 256
    assert await pixels(path, read=[(1, 1), (2, 2)]) == [[0, 0, 0, 255], [255, 255, 255, 255]]


async def test_resize_scales_content(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=4, height=4)
    await pixels(path, put=[(1, 1, *RED)])

    await call("resize_sprite", path="a.aseprite", width=8, height=8)

    info = await call("get_sprite_info", path="a.aseprite")
    assert (info["width"], info["height"]) == (8, 8)
    assert await pixels(path, read=[(2, 2), (3, 3), (1, 1), (4, 4)]) == [
        RED,
        RED,
        CLEAR,
        CLEAR,
    ]


async def test_crop_sprite(call, pixels, tmp_path: Path):
    path = tmp_path / "a.aseprite"
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    await pixels(path, put=[(5, 3, *RED)])

    await call("crop_sprite", path="a.aseprite", rect={"x": 4, "y": 2, "w": 3, "h": 3})

    info = await call("get_sprite_info", path="a.aseprite")
    assert (info["width"], info["height"]) == (3, 3)
    assert await pixels(path, read=[(1, 1), (0, 0)]) == [RED, CLEAR]


async def test_crop_outside_canvas_is_refused(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="does not overlap"):
        await call("crop_sprite", path="a.aseprite", rect={"x": 20, "y": 0, "w": 4, "h": 4})


async def test_save_copy_does_not_touch_source(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=5)
    source = tmp_path / "a.aseprite"
    before = (source.read_bytes(), source.stat().st_mtime_ns)

    result = await call("save_copy", path="a.aseprite", output="copy.png")

    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert result["output"] == str(tmp_path / "copy.png")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.aseprite", "copy.png"]
    copy_info = await call("get_sprite_info", path="copy.png")
    assert (copy_info["width"], copy_info["height"]) == (8, 5)


async def test_save_copy_refuses_existing_output(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    (tmp_path / "copy.png").write_bytes(b"keep me")

    with pytest.raises(ToolError, match="already exists"):
        await call("save_copy", path="a.aseprite", output="copy.png")

    assert (tmp_path / "copy.png").read_bytes() == b"keep me"


async def test_batch_save_copy_to_unknown_format_saves_nothing(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=4, height=4)
    before = (tmp_path / "a.aseprite").read_bytes()

    with pytest.raises(ToolError, match=r"op 2 \(save_copy\): Aseprite cannot save c\.xyz"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "resize_sprite", "args": {"width": 8, "height": 8}},
                {"tool": "save_copy", "args": {"output": "c.xyz"}},
            ],
        )

    assert (tmp_path / "a.aseprite").read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["a.aseprite"]


async def test_batch_save_copy_failing_in_aseprite_saves_nothing(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=4, height=4)
    before = (tmp_path / "a.aseprite").read_bytes()

    # FLI needs an indexed sprite, so Aseprite writes nothing for an RGB one.
    with pytest.raises(ToolError, match=r"op 2 \(save_copy\): Aseprite could not write a \.fli"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "resize_sprite", "args": {"width": 8, "height": 8}},
                {"tool": "save_copy", "args": {"output": "c.fli"}},
            ],
        )

    assert (tmp_path / "a.aseprite").read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["a.aseprite"]


async def test_batch_rejects_two_ops_writing_the_same_file(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=4, height=4)

    with pytest.raises(ToolError, match=r"op 1 \(save_copy\) and op 2 \(save_copy\) both write"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "save_copy", "args": {"output": "c.png"}},
                {"tool": "save_copy", "args": {"output": "./c.png"}},
            ],
        )

    assert [p.name for p in tmp_path.iterdir()] == ["a.aseprite"]


async def test_batch_three_ops_one_process(call, monkeypatch: pytest.MonkeyPatch):
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
            {"tool": "resize_sprite", "args": {"width": 16, "height": 16}},
            {"tool": "set_color_mode", "args": {"mode": "grayscale"}},
            {"tool": "get_sprite_info", "args": {}},
        ],
    )

    assert len(calls) == 1
    info = result["result"][2]
    assert (info["width"], info["color_mode"]) == (16, "grayscale")


async def test_batch_rejects_unknown_tool(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="paint_everything") as exc:
        await call("batch", path="a.aseprite", ops=[{"tool": "paint_everything", "args": {}}])

    assert "resize_sprite" in str(exc.value)


async def test_batch_rejects_create_sprite(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="'create_sprite' cannot be used in batch"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[{"tool": "create_sprite", "args": {"width": 4, "height": 4}}],
        )


async def test_batch_rejects_path_in_args(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match="op 1 .*path"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[{"tool": "get_sprite_info", "args": {"path": "other.aseprite"}}],
        )


async def test_batch_validates_args_like_direct_calls(call):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match=r"op 2 \(resize_sprite\): invalid arguments: width"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "get_sprite_info", "args": {}},
                {"tool": "resize_sprite", "args": {"width": 0, "height": 8}},
            ],
        )


async def test_batch_failure_keeps_file_unchanged(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=8)
    source = tmp_path / "a.aseprite"
    before = source.read_bytes()

    with pytest.raises(ToolError, match=r"op 2 \(crop_sprite\)"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "set_color_mode", "args": {"mode": "indexed"}},
                {"tool": "crop_sprite", "args": {"rect": {"x": 50, "y": 50, "w": 2, "h": 2}}},
            ],
        )

    assert source.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["a.aseprite"]
    info = await call("get_sprite_info", path="a.aseprite")
    assert info["color_mode"] == "rgb"


async def test_batch_save_copy_is_skipped_when_a_later_op_fails(call, tmp_path: Path):
    await call("create_sprite", path="a.aseprite", width=8, height=8)

    with pytest.raises(ToolError, match=r"op 2 \(crop_sprite\)"):
        await call(
            "batch",
            path="a.aseprite",
            ops=[
                {"tool": "save_copy", "args": {"output": "copy.png"}},
                {"tool": "crop_sprite", "args": {"rect": {"x": 50, "y": 50, "w": 2, "h": 2}}},
            ],
        )

    assert [p.name for p in tmp_path.iterdir()] == ["a.aseprite"]


async def test_tool_error_sets_is_error_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = load_settings({"ASEPRITE_MCP_ROOT": str(tmp_path)})
    monkeypatch.setattr(server, "get_settings", lambda: settings)

    async with create_connected_server_and_client_session(server.mcp) as client:
        result = await client.call_tool("get_sprite_info", {"path": "missing.aseprite"})

    assert result.isError is True
    assert "File not found" in result.content[0].text
