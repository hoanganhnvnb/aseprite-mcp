import asyncio
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from aseprite_mcp.config import Settings
from aseprite_mcp.errors import AsepriteError, ToolError
from aseprite_mcp.runner import (
    _kill_tree,
    _lock_key,
    _taskkill,
    replace_file,
    run_script,
    temp_sibling,
)
from helpers import make_settings

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
    settings = make_settings(tmp_path, aseprite=str(_wrapper(bin_dir)))
    return replace(settings, timeout=20.0, max_procs=4)


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


async def test_numbered_save_files_are_removed(settings: Settings, tmp_path: Path):
    target = tmp_path / "anim.png"
    target.write_text("old")

    with pytest.raises(AsepriteError, match="missing"):
        await run_script(SCRIPT, {"fake": "numbered"}, settings=settings, save_to=target)

    assert target.read_text() == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["anim.png", "bin"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
async def test_save_keeps_file_mode(settings: Settings, tmp_path: Path):
    target = tmp_path / "sprite.aseprite"
    target.write_text("old")
    target.chmod(0o640)

    await run_script(SCRIPT, {"fake": "ok", "write_save": "new"}, settings=settings, save_to=target)

    assert target.read_text() == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anything")
async def test_read_only_target_is_refused(settings: Settings, tmp_path: Path):
    target = tmp_path / "sprite.aseprite"
    target.write_text("old")
    target.chmod(0o444)

    with pytest.raises(ToolError, match="read-only"):
        await run_script(
            SCRIPT, {"fake": "ok", "write_save": "new"}, settings=settings, save_to=target
        )

    assert target.read_text() == "old"
    assert stat.S_IMODE(target.stat().st_mode) == 0o444


async def test_outputs_are_published(settings: Settings, tmp_path: Path):
    final = tmp_path / "copy.png"
    tmp = temp_sibling(final)

    await run_script(
        SCRIPT,
        {"fake": "ok", "write_files": [str(tmp)]},
        settings=settings,
        writes=[(tmp, final)],
    )

    assert final.read_text() == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bin", "copy.png"]


async def test_missing_output_leaves_earlier_outputs_alone(settings: Settings, tmp_path: Path):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    first.write_text("old a")
    second.write_text("old b")
    first_tmp, second_tmp = temp_sibling(first), temp_sibling(second)

    with pytest.raises(AsepriteError, match="could not write"):
        await run_script(
            SCRIPT,
            {"fake": "ok", "write_files": [str(first_tmp)]},
            settings=settings,
            writes=[(first_tmp, first), (second_tmp, second)],
        )

    assert first.read_text() == "old a"
    assert second.read_text() == "old b"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.png", "b.png", "bin"]


async def test_missing_output_keeps_the_sprite(settings: Settings, tmp_path: Path):
    target = tmp_path / "sprite.aseprite"
    target.write_text("old")
    output = tmp_path / "copy.png"

    with pytest.raises(AsepriteError, match="could not write"):
        await run_script(
            SCRIPT,
            {"fake": "ok", "write_save": "new"},
            settings=settings,
            save_to=target,
            writes=[(temp_sibling(output), output)],
        )

    assert target.read_text() == "old"


async def test_output_created_meanwhile_is_not_replaced(settings: Settings, tmp_path: Path):
    final = tmp_path / "copy.png"
    tmp = temp_sibling(final)
    final.write_text("theirs")

    with pytest.raises(ToolError, match="already exists"):
        await run_script(
            SCRIPT,
            {"fake": "ok", "write_files": [str(tmp)]},
            settings=settings,
            writes=[(tmp, final)],
            keep_existing=[final],
        )

    assert final.read_text() == "theirs"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bin", "copy.png"]


async def test_two_calls_cannot_both_create_one_output(settings: Settings, tmp_path: Path):
    final = tmp_path / "copy.png"

    async def create(text: str) -> None:
        tmp = temp_sibling(final)
        await run_script(
            SCRIPT,
            {"fake": "ok", "write_files": [str(tmp)], "file_text": text},
            settings=settings,
            writes=[(tmp, final)],
            keep_existing=[final],
        )

    results = await asyncio.gather(create("one"), create("two"), return_exceptions=True)

    failures = [r for r in results if isinstance(r, ToolError)]
    assert len(failures) == 1
    assert "already exists" in str(failures[0])
    assert final.read_text() == ("one" if results[0] is None else "two")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anything")
async def test_read_only_output_is_refused(settings: Settings, tmp_path: Path):
    final = tmp_path / "copy.png"
    final.write_text("old")
    final.chmod(0o444)
    tmp = temp_sibling(final)

    with pytest.raises(ToolError, match="read-only"):
        await run_script(
            SCRIPT,
            {"fake": "ok", "write_files": [str(tmp)]},
            settings=settings,
            writes=[(tmp, final)],
        )

    assert final.read_text() == "old"


def test_failed_replace_names_the_final_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    final = tmp_path / "copy.png"
    tmp = temp_sibling(final)
    tmp.write_text("new")

    def refuse(src, dst):
        raise PermissionError(13, "Permission denied", str(src))

    monkeypatch.setattr(os, "replace", refuse)

    with pytest.raises(ToolError) as caught:
        replace_file(tmp, final)

    assert str(caught.value) == f"Could not write {final}: Permission denied"
    assert not tmp.exists()


def test_lock_key_ignores_case_on_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert _lock_key(tmp_path / "Hero.aseprite") == _lock_key(tmp_path / "hero.aseprite")


def test_lock_key_is_the_same_through_dot_dot(tmp_path: Path):
    (tmp_path / "x").mkdir()

    assert _lock_key(tmp_path / "x" / ".." / "f.aseprite") == _lock_key(tmp_path / "f.aseprite")


def test_lock_key_follows_symlinks(tmp_path: Path):
    target = tmp_path / "f.aseprite"
    target.write_text("")
    link = tmp_path / "link.aseprite"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not available")

    assert _lock_key(link) == _lock_key(target)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX only")
async def test_kill_falls_back_to_the_child_when_killpg_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def refuse(pid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", refuse)
    started = time.monotonic()

    with pytest.raises(AsepriteError, match="timed out"):
        await run_script(
            SCRIPT, {"fake": "ok", "delay": 30}, settings=replace(settings, timeout=1.0)
        )

    assert time.monotonic() - started < 10


def test_taskkill_is_taken_from_system32(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = tmp_path / "System32" / "taskkill.exe"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    assert _taskkill() == str(exe)


def test_taskkill_falls_back_to_the_bare_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    assert _taskkill() == "taskkill"


class _Proc:
    pid = 4321

    def __init__(self) -> None:
        self.calls: list[str] = []

    def kill(self) -> None:
        self.calls.append("kill")

    async def wait(self) -> int:
        self.calls.append("wait")
        return -9


async def test_kill_falls_back_to_the_child_when_taskkill_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
):
    async def no_taskkill(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_taskkill)
    proc = _Proc()

    await _kill_tree(proc)  # type: ignore[arg-type]

    assert proc.calls == ["kill", "wait"]
