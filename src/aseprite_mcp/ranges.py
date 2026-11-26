import re
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictInt

# Far beyond any real animation; keeps "1-100000000" from building a huge list.
MAX_FRAME = 65535

_PART = re.compile(r"([0-9]+)(?:\s*-\s*([0-9]+))?")


def _frames(count: int) -> str:
    return f"{count} frame" if count == 1 else f"{count} frames"


def _check(frame: int, total: int | None) -> int:
    if frame < 1:
        raise ValueError(f"frame {frame} is out of range: frames start at 1")
    if frame > MAX_FRAME:
        raise ValueError(f"frame {frame} is out of range: frame numbers stop at {MAX_FRAME}")
    if total is not None and frame > total:
        raise ValueError(f"frame {frame} is out of range (sprite has {_frames(total)})")
    return frame


def parse_frames(spec: str | int, total: int | None = None) -> list[int] | Literal["all"]:
    """Parse "3", "1-4", "1-4,7" or "all" into sorted, unique 1-based frame numbers.

    Without `total` only the syntax is checked and "all" is returned as is.
    """
    if isinstance(spec, int):
        return [_check(spec, total)]
    text = spec.strip()
    if not text:
        raise ValueError("empty frame range: use '3', '1-4', '1-4,7' or 'all'")
    if text.lower() == "all":
        return "all" if total is None else list(range(1, total + 1))
    frames: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        match = _PART.fullmatch(part)
        if match is None:
            raise ValueError(f"invalid frame range {part!r}: use '3', '1-4', '1-4,7' or 'all'")
        start = _check(int(match[1]), total)
        end = _check(int(match[2]), total) if match[2] else start
        if start > end:
            raise ValueError(f"frame range {part!r} runs backwards")
        frames.update(range(start, end + 1))
    return sorted(frames)


FrameSpec = Annotated[
    str | StrictInt,
    AfterValidator(parse_frames),
    Field(description='Frames: a number, "1-4", "1-4,7" or "all" (1-based)'),
]
