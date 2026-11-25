from pathlib import Path

import pytest

from aseprite_mcp.config import Settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.paths import resolve_path


def make_settings(root: Path, sandbox: bool = False) -> Settings:
    return Settings(
        aseprite=None,
        root=root,
        sandbox=sandbox,
        timeout=60.0,
        max_procs=1,
        allow_lua=False,
        max_read_pixels=65536,
    )


def test_resolve_relative_against_root(tmp_path):
    s = make_settings(tmp_path)
    assert resolve_path("a/b.aseprite", s, must_exist=False) == tmp_path.resolve() / "a/b.aseprite"


def test_resolve_expands_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    s = make_settings(tmp_path / "other")
    assert resolve_path("~/x.aseprite", s, must_exist=False) == tmp_path.resolve() / "x.aseprite"


def test_resolve_sandbox_rejects_outside(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    s = make_settings(root, sandbox=True)
    with pytest.raises(ToolError):
        resolve_path("../x.aseprite", s, must_exist=False)
    with pytest.raises(ToolError):
        resolve_path(str(tmp_path / "x.aseprite"), s, must_exist=False)


def test_resolve_sandbox_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available")
    s = make_settings(root, sandbox=True)
    with pytest.raises(ToolError):
        resolve_path("link/x.aseprite", s, must_exist=False)


def test_resolve_sandbox_allows_inside(tmp_path):
    s = make_settings(tmp_path, sandbox=True)
    assert resolve_path("x.aseprite", s, must_exist=False) == tmp_path.resolve() / "x.aseprite"


def test_resolve_open_mode_allows_outside(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    s = make_settings(root)
    assert resolve_path("../x.aseprite", s, must_exist=False) == tmp_path.resolve() / "x.aseprite"


def test_resolve_keeps_spaces_and_unicode(tmp_path):
    s = make_settings(tmp_path)
    p = resolve_path("thư mục/ảnh 1.aseprite", s, must_exist=False)
    assert p == tmp_path.resolve() / "thư mục" / "ảnh 1.aseprite"


def test_resolve_missing_raises(tmp_path):
    s = make_settings(tmp_path)
    with pytest.raises(ToolError, match="File not found"):
        resolve_path("nope.aseprite", s, must_exist=True)


def test_resolve_existing_ok(tmp_path):
    (tmp_path / "a.aseprite").write_text("")
    s = make_settings(tmp_path)
    assert resolve_path("a.aseprite", s, must_exist=True).name == "a.aseprite"


def test_resolve_empty_path_raises(tmp_path):
    with pytest.raises(ToolError):
        resolve_path("  ", make_settings(tmp_path), must_exist=False)


def test_resolve_sandbox_rejects_sibling_with_shared_prefix(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "root2").mkdir()
    with pytest.raises(ToolError):
        resolve_path("../root2/x.aseprite", make_settings(root, sandbox=True), must_exist=False)


def test_resolve_sandbox_rejects_home_outside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ToolError):
        resolve_path("~/x.aseprite", make_settings(root, sandbox=True), must_exist=False)


def test_resolve_must_exist_accepts_directory(tmp_path):
    (tmp_path / "d").mkdir()
    assert resolve_path("d", make_settings(tmp_path), must_exist=True).is_dir()


def test_resolve_unknown_user_raises_tool_error(tmp_path):
    with pytest.raises(ToolError):
        resolve_path("~no_such_user_xyz/x.aseprite", make_settings(tmp_path), must_exist=False)


def test_resolve_nul_byte_raises_tool_error(tmp_path):
    with pytest.raises(ToolError):
        resolve_path("a\0b.aseprite", make_settings(tmp_path), must_exist=False)
