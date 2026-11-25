import math
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_READ_PIXELS = 65536
# Pixels check_animation may scan for overlaps in one call (about a second of work).
DEFAULT_MAX_SCAN_PIXELS = 16 * 1024 * 1024
DEFAULT_MAX_BATCH_OPS = 1000
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    aseprite: str | None
    root: Path
    sandbox: bool
    timeout: float
    max_procs: int
    allow_lua: bool
    max_read_pixels: int
    max_scan_pixels: int = DEFAULT_MAX_SCAN_PIXELS
    max_batch_ops: int = DEFAULT_MAX_BATCH_OPS


def _flag(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUE


def _positive_int(value: str | None, default: int) -> int:
    try:
        n = int(value) if value is not None else default
    except ValueError:
        return default
    return n if n >= 1 else default


def _timeout(value: str | None) -> float:
    try:
        seconds = float(value) if value is not None else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT
    return seconds if math.isfinite(seconds) and seconds > 0 else DEFAULT_TIMEOUT


def find_aseprite(env: Mapping[str, str], platform: str = sys.platform) -> str | None:
    configured = env.get("ASEPRITE_PATH", "").strip()
    if configured:
        # An explicit setting never falls through to autodetection, so a typo
        # shows up as "not found" instead of silently running another binary.
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path)
        return shutil.which(str(path), path=env.get("PATH", ""))

    on_path = shutil.which("aseprite", path=env.get("PATH", ""))
    if on_path:
        return on_path

    for candidate in _known_locations(env, platform):
        if candidate.is_file():
            return str(candidate)
    return None


def _known_locations(env: Mapping[str, str], platform: str) -> list[Path]:
    home = Path.home()
    steam_tail = Path("steamapps/common/Aseprite")
    if platform == "darwin":
        return [
            Path("/Applications/Aseprite.app/Contents/MacOS/aseprite"),
            home
            / "Library/Application Support/Steam"
            / steam_tail
            / "Aseprite.app/Contents/MacOS/aseprite",
        ]
    if platform == "win32":
        found = []
        for var, tail in (
            ("ProgramFiles", Path("Aseprite/Aseprite.exe")),
            ("ProgramFiles(x86)", Path("Steam") / steam_tail / "Aseprite.exe"),
        ):
            if env.get(var):
                found.append(Path(env[var]) / tail)
        return found
    return [
        home / ".steam/steam" / steam_tail / "aseprite",
        home / ".local/share/Steam" / steam_tail / "aseprite",
        Path("/usr/bin/aseprite"),
    ]


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    root = env.get("ASEPRITE_MCP_ROOT", "").strip()
    return Settings(
        aseprite=find_aseprite(env),
        root=Path(root).expanduser().resolve() if root else Path.cwd(),
        sandbox=_flag(env.get("ASEPRITE_MCP_SANDBOX")),
        timeout=_timeout(env.get("ASEPRITE_TIMEOUT_SECONDS")),
        max_procs=_positive_int(env.get("ASEPRITE_MCP_MAX_PROCS"), min(4, os.cpu_count() or 1)),
        allow_lua=_flag(env.get("ASEPRITE_MCP_ALLOW_LUA")),
        max_read_pixels=_positive_int(
            env.get("ASEPRITE_MCP_MAX_READ_PIXELS"), DEFAULT_MAX_READ_PIXELS
        ),
        max_scan_pixels=_positive_int(
            env.get("ASEPRITE_MCP_MAX_SCAN_PIXELS"), DEFAULT_MAX_SCAN_PIXELS
        ),
        max_batch_ops=_positive_int(env.get("ASEPRITE_MCP_MAX_BATCH_OPS"), DEFAULT_MAX_BATCH_OPS),
    )
