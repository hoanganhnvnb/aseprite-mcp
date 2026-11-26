import pytest
from pydantic import TypeAdapter, ValidationError

from aseprite_mcp.ranges import FrameSpec, parse_frames


def test_parse_frames_single():
    assert parse_frames("3") == [3]


def test_parse_frames_int():
    assert parse_frames(2) == [2]


def test_parse_frames_range():
    assert parse_frames("1-4") == [1, 2, 3, 4]


def test_parse_frames_mixed_list_with_spaces():
    assert parse_frames(" 1-3 , 7 ") == [1, 2, 3, 7]


def test_parse_frames_sorts_and_dedupes():
    assert parse_frames("5,1-4,3") == [1, 2, 3, 4, 5]


def test_parse_frames_all_without_total():
    assert parse_frames("all") == "all"


def test_parse_frames_all_with_total():
    assert parse_frames("all", total=3) == [1, 2, 3]


def test_parse_frames_checks_total():
    with pytest.raises(ValueError, match="frame 5"):
        parse_frames("2-5", total=4)


def test_parse_frames_empty_fails():
    with pytest.raises(ValueError, match="empty"):
        parse_frames("  ")


def test_parse_frames_zero_fails():
    with pytest.raises(ValueError, match="frame 0"):
        parse_frames("0")


def test_parse_frames_zero_int_fails():
    with pytest.raises(ValueError, match="frame 0"):
        parse_frames(0)


def test_parse_frames_negative_fails():
    with pytest.raises(ValueError, match="'-2'"):
        parse_frames("-2")


def test_parse_frames_backwards_range_fails():
    with pytest.raises(ValueError, match="'5-3'"):
        parse_frames("5-3")


def test_parse_frames_non_numeric_fails():
    with pytest.raises(ValueError, match="'two'"):
        parse_frames("1,two")


def test_parse_frames_open_range_fails():
    with pytest.raises(ValueError, match="'1-'"):
        parse_frames("1-")


def test_parse_frames_letter_range_fails():
    with pytest.raises(ValueError, match="'a-b'"):
        parse_frames("a-b")


def test_parse_frames_huge_number_fails():
    with pytest.raises(ValueError, match="65535"):
        parse_frames("1-100000000")


def test_frame_spec_normalises_input():
    adapter = TypeAdapter(FrameSpec)

    assert adapter.validate_python("2,1") == [1, 2]
    assert adapter.validate_python(4) == [4]
    assert adapter.validate_python("all") == "all"


def test_frame_spec_rejects_bad_range():
    with pytest.raises(ValidationError, match="'5-3'"):
        TypeAdapter(FrameSpec).validate_python("5-3")


def test_frame_spec_schema_is_string_or_integer():
    schema = TypeAdapter(FrameSpec).json_schema()

    assert {item["type"] for item in schema["anyOf"]} == {"string", "integer"}
    assert "1-4,7" in schema["description"]


def test_frame_spec_rejects_a_bool():
    with pytest.raises(ValidationError):
        TypeAdapter(FrameSpec).validate_python(True)


def test_frame_spec_rejects_a_float():
    with pytest.raises(ValidationError):
        TypeAdapter(FrameSpec).validate_python(2.0)


def test_parse_frames_says_1_frame_in_singular():
    with pytest.raises(ValueError, match=r"sprite has 1 frame\)"):
        parse_frames(2, total=1)


def test_parse_frames_says_frames_in_plural():
    with pytest.raises(ValueError, match=r"sprite has 3 frames\)"):
        parse_frames(4, total=3)
