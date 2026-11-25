from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from .colors import parse_color


class Rect(BaseModel):
    """Rectangle in sprite pixels; x and y may be negative."""

    x: int = Field(ge=-65535, le=65535)
    y: int = Field(ge=-65535, le=65535)
    w: int = Field(ge=1, le=131072)
    h: int = Field(ge=1, le=131072)


def _check_color(value: str) -> str:
    parse_color(value)
    return value


Color = Annotated[
    str,
    AfterValidator(_check_color),
    Field(description="'#RRGGBB', '#RRGGBBAA' or 'transparent'"),
]


# Strict so that strings and floats are rejected instead of coerced.
Coord = Annotated[int, Field(strict=True, ge=-65535, le=65535)]


class Point(BaseModel):
    """A pixel position in sprite coordinates."""

    x: Coord
    y: Coord


class Pixel(BaseModel):
    x: Coord
    y: Coord
    color: Color
