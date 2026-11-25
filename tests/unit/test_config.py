import os
import sys
from pathlib import Path

import pytest

from aseprite_mcp.config import find_aseprite, load_settings


@pytest.mark.parametrize("raw", ["abc", "inf", "-1", "nan", "0", ""])
def test_timeout_invalid_falls_back(raw):
    assert load_settings({"ASEPRITE_TIMEOUT_SECONDS": raw}).timeout == 60.0


def test_timeout_valid():
    assert load_settings({"ASEPRITE_TIMEOUT_SECONDS": "12.5"}).timeout == 12.5


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = load_settings({})
    assert s.root == Path.cwd()
    assert s.sandbox is False
    assert s.allow_lua is False
    assert s.max_read_pixels == 65536
    assert s.max_scan_pixels == 16 * 1024 * 1024
    assert s.max_procs == min(4, os.cpu_count() or 1)


def test_numeric_and_bool_parsing(tmp_path):
    s = load_settings(
        {
            "ASEPRITE_MCP_ROOT": str(tmp_path),
            "ASEPRITE_MCP_SANDBOX": "Yes",
            "ASEPRITE_MCP_ALLOW_LUA": "1",
            "ASEPRITE_MCP_MAX_PROCS": "2",
            "ASEPRITE_MCP_MAX_READ_PIXELS": "100",
        }
    )
    assert (s.root, s.sandbox, s.allow_lua, s.max_procs, s.max_read_pixels) == (
        tmp_path,
        True,
        True,
        2,
        100,
    )


@pytest.mark.parametrize("raw", ["0", "-3", "x", ""])
def test_invalid_ints_fall_back(raw):
    s = load_settings({"ASEPRITE_MCP_MAX_PROCS": raw, "ASEPRITE_MCP_MAX_READ_PIXELS": raw})
    assert s.max_procs == min(4, os.cpu_count() or 1)
    assert s.max_read_pixels == 65536


def test_scan_pixel_limit_from_env():
    assert load_settings({"ASEPRITE_MCP_MAX_SCAN_PIXELS": "500"}).max_scan_pixels == 500


def test_find_aseprite_env_wins(tmp_path):
    exe = tmp_path / "my aseprite"
    exe.write_text("")
    assert find_aseprite({"ASEPRITE_PATH": str(exe)}, "linux") == str(exe)


def test_find_aseprite_bad_env_path_returns_none(tmp_path):
    assert find_aseprite({"ASEPRITE_PATH": str(tmp_path / "missing")}, "linux") is None


def test_find_aseprite_uses_path_lookup(tmp_path):
    exe = tmp_path / ("aseprite.exe" if sys.platform == "win32" else "aseprite")
    exe.write_text("")
    if sys.platform != "win32":
        exe.chmod(0o755)
    found = find_aseprite({"PATH": str(tmp_path)}, "linux")
    assert found is not None and Path(found) == exe


def test_find_aseprite_known_location(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert find_aseprite({"PATH": ""}, "darwin") is None
    exe = (
        tmp_path
        / "Library/Application Support/Steam/steamapps/common/Aseprite"
        / "Aseprite.app/Contents/MacOS/aseprite"
    )
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert find_aseprite({"PATH": ""}, "darwin") == str(exe)


def test_find_aseprite_windows_uses_env_mapping(tmp_path):
    exe = tmp_path / "Aseprite" / "Aseprite.exe"
    exe.parent.mkdir()
    exe.write_text("")
    env = {"PATH": "", "ProgramFiles": str(tmp_path)}
    assert find_aseprite(env, "win32") == str(exe)
