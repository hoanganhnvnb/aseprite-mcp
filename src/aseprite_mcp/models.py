from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from .colors import parse_color


class Rect(BaseModel):
    """Rectangle in sprite pixels; x and y may be negative."""

    x: int
    y: int
    w: int = Field(ge=1)
    h: int = Field(ge=1)


def _check_color(value: str) -> str:
    parse_color(value)
    return value


Color = Annotated[
    str,
    AfterValidator(_check_color),
    Field(description="'#RRGGBB', '#RRGGBBAA' or 'transparent'"),
]
