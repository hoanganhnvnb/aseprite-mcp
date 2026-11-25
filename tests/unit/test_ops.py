from aseprite_mcp.ops import op_files, op_owners
from aseprite_mcp.tools._registry import BATCHABLE


def test_one_op_loads_only_its_file():
    assert op_files(["draw_rect"]) == ["draw.lua"]


def test_ops_from_two_files_load_both():
    assert op_files(["read_pixels", "draw_rect", "draw_line"]) == ["draw.lua", "read.lua"]


def test_run_lua_loads_every_op_file():
    files = op_files(["run_lua"])

    assert len(files) == 14
    assert files == sorted(set(op_owners().values()))


def test_unknown_op_loads_no_file():
    assert op_files(["nope"]) == []


def test_every_batchable_op_has_a_file():
    missing = {op for op, _, _ in BATCHABLE.values()} - op_owners().keys()

    assert missing == set()


def test_ops_called_outside_the_registry_have_a_file():
    owners = op_owners()

    assert owners["render_frames"] == "read.lua"
    assert owners["export_sheet"] == "export.lua"
    assert owners["import_image"] == "export.lua"
    assert owners["run_lua"] == "misc.lua"
    assert owners["_ping"] == "sprite.lua"
