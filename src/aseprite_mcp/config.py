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
MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 3600.0
MAX_PROCS = 32
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    pass


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


def _flag(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name, "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE or value == "":
        return False
    raise ConfigError(
        f"{name}={env[name]!r} is not a yes/no value; use 1/true/yes/on or 0/false/no/off"
    )


def _int(env: Mapping[str, str], name: str, default: int, high: int) -> int:
    value = env.get(name, "").strip()
    if not value:
        return default
    try:
        n = int(value)
    except ValueError:
        n = 0
    if not 1 <= n <= high:
        raise ConfigError(f"{name}={env[name]!r} must be a whole number from 1 to {high}")
    return n


def _timeout(env: Mapping[str, str]) -> float:
    name = "ASEPRITE_TIMEOUT_SECONDS"
    value = env.get(name, "").strip()
    if not value:
        return DEFAULT_TIMEOUT
    try:
        seconds = float(value)
    except ValueError:
        seconds = math.nan
    if not MIN_TIMEOUT <= seconds <= MAX_TIMEOUT:
        raise ConfigError(
            f"{name}={env[name]!r} must be a number of seconds from {MIN_TIMEOUT:g} to {MAX_TIMEOUT:g}"
        )
    return seconds


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
    """Read the settings from the environment; raises ConfigError on a value it cannot use."""
    root = env.get("ASEPRITE_MCP_ROOT", "").strip()
    return Settings(
        aseprite=find_aseprite(env),
        root=Path(root).expanduser().resolve() if root else Path.cwd(),
        sandbox=_flag(env, "ASEPRITE_MCP_SANDBOX"),
        timeout=_timeout(env),
        max_procs=_int(env, "ASEPRITE_MCP_MAX_PROCS", min(4, os.cpu_count() or 1), MAX_PROCS),
        allow_lua=_flag(env, "ASEPRITE_MCP_ALLOW_LUA"),
        max_read_pixels=_int(
            env, "ASEPRITE_MCP_MAX_READ_PIXELS", DEFAULT_MAX_READ_PIXELS, 4096 * 4096
        ),
        max_scan_pixels=_int(env, "ASEPRITE_MCP_MAX_SCAN_PIXELS", DEFAULT_MAX_SCAN_PIXELS, 1 << 30),
        max_batch_ops=_int(env, "ASEPRITE_MCP_MAX_BATCH_OPS", DEFAULT_MAX_BATCH_OPS, 100_000),
    )
