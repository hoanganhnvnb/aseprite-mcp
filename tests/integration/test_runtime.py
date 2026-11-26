from pathlib import Path

import pytest

from aseprite_mcp.config import Settings
from aseprite_mcp.errors import AsepriteError
from aseprite_mcp.ops import Op, run_op, run_ops
from aseprite_mcp.runner import run_script

PRELUDE_SPEC = Path(__file__).parent.parent / "lua" / "prelude_spec.lua"
EASING_SPEC = Path(__file__).parent.parent / "lua" / "easing_spec.lua"
BAYER_SPEC = Path(__file__).parent.parent / "lua" / "bayer_spec.lua"


async def test_create_and_info(ase_settings: Settings, make_sprite, tmp_path: Path):
    path = await make_sprite(tmp_path, w=16, h=12, layers=["bg", 'a"b\nc', "été ☃"])

    info = await run_op(path, "sprite_info", {}, settings=ase_settings, mutates=False)

    assert (info["width"], info["height"], info["color_mode"]) == (16, 12, "rgb")
    assert info["frames"] == [{"index": 1, "duration_ms": 100}]
    assert [layer["name"] for layer in info["layers"]] == ["bg", 'a"b\nc', "été ☃"]
    assert info["layers"][1] == {
        "name": 'a"b\nc',
        "path": 'a"b\nc',
        "type": "normal",
        "visible": True,
        "locked": False,
        "is_background": False,
        "opacity": 255,
        "blend_mode": "normal",
        "children": [],
    }
    assert info["tags"] == []
    assert info["slice_count"] == 0


async def test_info_reports_color_mode(ase_settings: Settings, make_sprite, tmp_path: Path):
    indexed = await make_sprite(tmp_path, mode="indexed", name="i.aseprite")
    gray = await make_sprite(tmp_path, mode="grayscale", name="g.aseprite")

    indexed_info = await run_op(indexed, "sprite_info", {}, settings=ase_settings, mutates=False)
    gray_info = await run_op(gray, "sprite_info", {}, settings=ase_settings, mutates=False)

    assert indexed_info["color_mode"] == "indexed"
    assert indexed_info["palette_size"] > 1
    assert gray_info["color_mode"] == "grayscale"


async def test_create_rejects_unknown_color_mode(ase_settings: Settings, tmp_path: Path):
    path = tmp_path / "bad.aseprite"
    create = {"width": 8, "height": 8, "color_mode": "cmyk"}

    with pytest.raises(AsepriteError, match="cmyk"):
        await run_ops(path, [], settings=ase_settings, create=create)
    assert not path.exists()


async def test_create_rejects_fractional_width(ase_settings: Settings, tmp_path: Path):
    path = tmp_path / "bad.aseprite"
    create = {"width": 16.5, "height": 8, "color_mode": "rgb"}

    with pytest.raises(AsepriteError, match="positive integers"):
        await run_ops(path, [], settings=ase_settings, create=create)
    assert not path.exists()


async def test_multi_frame_sprite_cannot_save_as_png(ase_settings: Settings, tmp_path: Path):
    path = tmp_path / "anim.png"
    create = {"width": 8, "height": 8, "color_mode": "rgb", "frames": 2}

    with pytest.raises(AsepriteError, match=r"\.aseprite or \.gif"):
        await run_ops(path, [], settings=ase_settings, create=create)
    assert list(tmp_path.iterdir()) == []


async def test_params_keep_fractions(ase_settings: Settings):
    echo = {"f": 1.5, "g": -0.25, "n": 16}

    result = await run_op(None, "_ping", {"echo": echo}, settings=ase_settings, mutates=False)

    assert result["echo"] == {"f": 1.5, "g": -0.25, "n": 16}
    assert isinstance(result["echo"]["n"], int)


async def test_ping_without_sprite(ase_settings: Settings):
    result = await run_op(None, "_ping", {}, settings=ase_settings, mutates=False)

    assert isinstance(result["api"], int)
    assert result["version"].count(".") >= 2


async def test_lua_error_reported(ase_settings: Settings, make_sprite, tmp_path: Path):
    path = await make_sprite(tmp_path)
    before = path.read_bytes()

    with pytest.raises(AsepriteError) as exc:
        await run_op(path, "_ping", {"fail": "boom"}, settings=ase_settings, mutates=True)

    assert str(exc.value) == "boom"
    assert path.read_bytes() == before


async def test_bug_error_has_traceback(ase_settings: Settings):
    with pytest.raises(AsepriteError, match=r"ops/sprite\.lua:\d+") as exc:
        await run_op(None, "_ping", {"crash": True}, settings=ase_settings, mutates=False)

    assert "traceback" in str(exc.value)


async def test_unknown_op(ase_settings: Settings):
    with pytest.raises(AsepriteError, match="unknown op 'nope'"):
        await run_op(None, "nope", {}, settings=ase_settings, mutates=False)


async def test_mutating_batch_saves_file(ase_settings: Settings, make_sprite, tmp_path: Path):
    path = await make_sprite(tmp_path)
    inode = path.stat().st_ino

    results = await run_ops(path, [Op("_ping", {}, mutates=True)], settings=ase_settings)

    assert len(results) == 1
    assert path.stat().st_ino != inode
    assert [p.name for p in tmp_path.iterdir()] == ["sprite.aseprite"]


async def test_batch_rolls_back_on_failure(ase_settings: Settings, make_sprite, tmp_path: Path):
    path = await make_sprite(tmp_path)
    before = path.read_bytes()
    inode = path.stat().st_ino
    ops = [Op("_ping", {}, mutates=True), Op("_ping", {"fail": "second op failed"}, mutates=False)]

    with pytest.raises(AsepriteError, match="second op failed"):
        await run_ops(path, ops, settings=ase_settings)

    assert path.read_bytes() == before
    assert path.stat().st_ino == inode
    assert [p.name for p in tmp_path.iterdir()] == ["sprite.aseprite"]


async def test_prelude_spec(ase_settings: Settings):
    result = await run_script(PRELUDE_SPEC, {}, settings=ase_settings)

    assert result.data["checks"] > 10


async def test_easing_spec(ase_settings: Settings):
    result = await run_script(EASING_SPEC, {}, settings=ase_settings)

    assert result.data["checks"] > 20


async def test_bayer_spec(ase_settings: Settings):
    result = await run_script(BAYER_SPEC, {}, settings=ase_settings)

    assert result.data["checks"] == 8
