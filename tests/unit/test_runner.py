import asyncio
import os
import signal
import stat
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from aseprite_mcp.config import Settings
from aseprite_mcp.errors import AsepriteError
from aseprite_mcp.runner import run_script

FAKE = Path(__file__).parent.parent / "fake_aseprite.py"
SCRIPT = Path("unused.lua")


def _wrapper(directory: Path) -> Path:
    if sys.platform == "win32":
        path = directory / "aseprite.cmd"
        path.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
    else:
        path = directory / "aseprite"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return Settings(
        aseprite=str(_wrapper(bin_dir)),
        root=tmp_path,
        sandbox=False,
        timeout=20.0,
        max_procs=4,
        allow_lua=False,
        max_read_pixels=65536,
    )


def _events(log: Path) -> dict[str, float]:
    return {line.split()[0]: float(line.split()[1]) for line in log.read_text().splitlines()}


async def test_ok_returns_data(settings: Settings):
    result = await run_script(SCRIPT, {"fake": "ok"}, settings=settings)
    assert result.data["ok"] is True
    assert result.data["saved"] is False
    assert result.elapsed >= 0


async def test_crash_raises_with_stderr(settings: Settings):
    with pytest.raises(AsepriteError, match="boom: something went wrong"):
        await run_script(SCRIPT, {"fake": "crash"}, settings=settings)


async def test_noresult_raises(settings: Settings):
    with pytest.raises(AsepriteError, match="result"):
        await run_script(SCRIPT, {"fake": "noresult"}, settings=settings)


async def test_result_error_is_raised(settings: Settings):
    with pytest.raises(AsepriteError, match="no such layer"):
        await run_script(SCRIPT, {"fake": "fail"}, settings=settings)


async def test_unicode_output_decodes(settings: Settings):
    result = await run_script(SCRIPT, {"fake": "unicode"}, settings=settings)
    assert "éè ☃" in result.stdout
    assert "�" in result.stdout


async def test_missing_binary_message(settings: Settings):
    with pytest.raises(AsepriteError, match="ASEPRITE_PATH"):
        await run_script(SCRIPT, {"fake": "ok"}, settings=replace(settings, aseprite=None))


async def test_timeout_kills_tree(settings: Settings, tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    params = {"fake": "sleep", "pid_file": str(pid_file)}
    started = time.monotonic()
    with pytest.raises(AsepriteError, match=r"timed out.*ASEPRITE_TIMEOUT_SECONDS"):
        await run_script(SCRIPT, params, settings=replace(settings, timeout=1.5))
    assert time.monotonic() - started < 10
    if sys.platform == "win32":
        pytest.skip("grandchild liveness check is only implemented for POSIX")
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    os.kill(pid, signal.SIGKILL)
    pytest.fail("grandchild survived the timeout")


async def test_same_file_serialized(settings: Settings, tmp_path: Path):
    target = tmp_path / "a.aseprite"
    logs = [tmp_path / "one.log", tmp_path / "two.log"]
    await asyncio.gather(
        *(
            run_script(
                SCRIPT,
                {"fake": "ok", "delay": 0.4, "log": str(log)},
                settings=settings,
                lock_paths=[target],
            )
            for log in logs
        )
    )
    first, second = sorted((_events(log) for log in logs), key=lambda e: e["start"])
    assert second["start"] >= first["end"]


async def test_lock_is_released_after_failure(settings: Settings, tmp_path: Path):
    target = tmp_path / "a.aseprite"
    with pytest.raises(AsepriteError):
        await run_script(SCRIPT, {"fake": "crash"}, settings=settings, lock_paths=[target])
    result = await asyncio.wait_for(
        run_script(SCRIPT, {"fake": "ok"}, settings=settings, lock_paths=[target]), 10
    )
    assert result.data["ok"]


async def test_different_files_parallel(settings: Settings, tmp_path: Path):
    logs = [tmp_path / "one.log", tmp_path / "two.log"]
    await asyncio.gather(
        *(
            run_script(
                SCRIPT,
                {"fake": "ok", "delay": 1.0, "log": str(log)},
                settings=settings,
                lock_paths=[tmp_path / f"{i}.aseprite"],
            )
            for i, log in enumerate(logs)
        )
    )
    a, b = (_events(log) for log in logs)
    assert max(a["start"], b["start"]) < min(a["end"], b["end"])


async def test_opposite_lock_order_does_not_deadlock(settings: Settings, tmp_path: Path):
    a, b = tmp_path / "a.aseprite", tmp_path / "b.aseprite"
    await asyncio.wait_for(
        asyncio.gather(
            run_script(SCRIPT, {"fake": "ok", "delay": 0.2}, settings=settings, lock_paths=[a, b]),
            run_script(SCRIPT, {"fake": "ok", "delay": 0.2}, settings=settings, lock_paths=[b, a]),
        ),
        15,
    )


async def test_save_replaces_atomically(settings: Settings, tmp_path: Path):
    target = tmp_path / "sprite.aseprite"
    target.write_text("old")
    result = await run_script(
        SCRIPT,
        {"fake": "ok", "write_save": "new"},
        settings=settings,
        lock_paths=[target],
        save_to=target,
    )
    assert result.data["saved"] is True
    assert target.read_text() == "new"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


async def test_not_saved_leaves_original(settings: Settings, tmp_path: Path):
    target = tmp_path / "sprite.aseprite"
    target.write_text("old")
    await run_script(SCRIPT, {"fake": "ok"}, settings=settings, save_to=target)
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


async def test_timeout_keeps_original(settings: Settings, tmp_path: Path):
    target = tmp_path / "sprite.aseprite"
    target.write_text("old")
    params = {"fake": "sleep", "pid_file": str(tmp_path / "pid")}
    with pytest.raises(AsepriteError, match="timed out"):
        await run_script(SCRIPT, params, settings=replace(settings, timeout=1.0), save_to=target)
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []
