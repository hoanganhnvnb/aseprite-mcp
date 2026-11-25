import asyncio
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
import weakref
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import AsepriteError, ToolError

LUA_DIR = Path(__file__).parent / "lua"
STDERR_TAIL = 2048


@dataclass
class RunResult:
    data: dict[str, Any]
    stdout: str
    stderr: str
    elapsed: float


class _LoopState:
    """Locks and semaphores for one event loop."""

    def __init__(self) -> None:
        self.semaphores: dict[int, asyncio.Semaphore] = {}
        self.file_locks: dict[str, asyncio.Lock] = {}


_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopState] = (
    weakref.WeakKeyDictionary()
)


def _state() -> _LoopState:
    loop = asyncio.get_running_loop()
    state = _states.get(loop)
    if state is None:
        state = _states[loop] = _LoopState()
    return state


def _lock_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _tail(text: str) -> str:
    return text[-STDERR_TAIL:].strip()


def temp_sibling(path: Path) -> Path:
    token = secrets.token_hex(4)
    return path.with_name(f".{path.stem}.{token}.tmp{path.suffix}")


def check_writable(path: Path) -> None:
    if path.exists() and not os.access(path, os.W_OK):
        raise ToolError(f"{path} is read-only; make it writable first (nothing was changed)")


def replace_file(tmp: Path, final: Path) -> None:
    # The new file takes the place of the old one rather than overwriting it, so it
    # gets the old file's permission bits here; hard links to the old file are broken.
    if sys.platform != "win32":
        try:
            os.chmod(tmp, stat.S_IMODE(final.stat().st_mode))
        except OSError:
            pass
    os.replace(tmp, final)


def remove_temp_files(tmp: Path) -> None:
    # Saving a multi-frame sprite to a single-image format makes Aseprite write
    # numbered siblings (.x.token.tmp1.png, ...) next to the requested name.
    prefix = tmp.name.removesuffix(tmp.suffix)
    try:
        entries = list(os.scandir(tmp.parent))
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(prefix) and entry.is_file(follow_symlinks=False):
            Path(entry.path).unlink(missing_ok=True)


def _taskkill() -> str:
    # By full path so a taskkill.exe in the working directory or on PATH is not picked up.
    system_root = os.environ.get("SystemRoot")
    if system_root:
        path = Path(system_root) / "System32" / "taskkill.exe"
        if path.is_file():
            return str(path)
    return "taskkill"


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            _taskkill(),
            "/F",
            "/T",
            "/PID",
            str(proc.pid),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await killer.wait()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can answer EPERM for a group whose leader already exited; the
            # child itself is still killed below.
            pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    await proc.wait()


def _spawn_options() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


async def _execute(argv: list[str], timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **_spawn_options(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        await asyncio.shield(_kill_tree(proc))
        raise AsepriteError(
            f"Aseprite timed out after {timeout:g}s and was killed. "
            "Raise ASEPRITE_TIMEOUT_SECONDS if the operation needs longer."
        ) from None
    except BaseException:
        await asyncio.shield(_kill_tree(proc))
        raise
    return (
        proc.returncode if proc.returncode is not None else -1,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


def _read_result(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def run_script(
    script: Path,
    params: dict[str, Any],
    *,
    settings: Settings,
    lock_paths: Sequence[Path] = (),
    open_file: Path | None = None,
    save_to: Path | None = None,
) -> RunResult:
    if settings.aseprite is None:
        raise AsepriteError(
            "Aseprite was not found. Install Aseprite (https://www.aseprite.org) and set "
            "ASEPRITE_PATH to the executable, or put it on PATH."
        )

    state = _state()
    semaphore = state.semaphores.setdefault(
        settings.max_procs, asyncio.Semaphore(settings.max_procs)
    )
    keys = sorted({_lock_key(p) for p in lock_paths})

    async with AsyncExitStack() as stack:
        for key in keys:
            await stack.enter_async_context(state.file_locks.setdefault(key, asyncio.Lock()))
        await stack.enter_async_context(semaphore)
        if save_to is not None:
            check_writable(save_to)
        return await _run_locked(script, params, settings, open_file, save_to)


async def _run_locked(
    script: Path,
    params: dict[str, Any],
    settings: Settings,
    open_file: Path | None,
    save_to: Path | None,
) -> RunResult:
    save_tmp = temp_sibling(save_to) if save_to is not None else None
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="aseprite-mcp-") as tmp:
            result_path = Path(tmp) / "result.json"
            params_path = Path(tmp) / "params.json"
            payload = {**params, "result_path": str(result_path), "lua_dir": str(LUA_DIR)}
            if save_tmp is not None:
                payload["save_tmp"] = str(save_tmp)
            if open_file is not None:
                # Opened from Lua: on the command line, walk_1.png would load
                # walk_2.png and the rest of the numbered sequence as frames.
                payload["open_file"] = str(open_file)
            params_path.write_text(json.dumps(payload), encoding="utf-8")

            argv = [
                settings.aseprite,
                "--batch",
                "--script-param",
                f"params={params_path}",
                "--script",
                str(script),
            ]
            code, stdout, stderr = await _execute(argv, settings.timeout)
            data = _read_result(result_path)

        if data is None:
            detail = _tail(stderr) or _tail(stdout) or "no output"
            if code != 0:
                raise AsepriteError(f"Aseprite exited with code {code}: {detail}")
            raise AsepriteError(f"Aseprite finished without writing a result: {detail}")
        if not data.get("ok", False):
            raise AsepriteError(
                str(data.get("error") or _tail(stderr) or "Aseprite reported failure")
            )

        if save_to is not None and save_tmp is not None and data.get("saved"):
            if not save_tmp.exists():
                raise AsepriteError(f"Aseprite reported a save but {save_tmp.name} is missing")
            replace_file(save_tmp, save_to)
        return RunResult(data, stdout, stderr, time.monotonic() - started)
    finally:
        if save_tmp is not None:
            remove_temp_files(save_tmp)
