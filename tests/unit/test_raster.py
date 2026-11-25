import pytest

from aseprite_mcp.raster import ascii_art, isometric_box, merge, outline, subtract, union


def test_merge_joins_touching_and_overlapping_spans():
    assert merge([(4, 6), (0, 2), (3, 3), (8, 9), (9, 12)]) == [(0, 6), (8, 12)]


def test_subtract_cuts_holes():
    assert subtract([(0, 9)], [(2, 3), (7, 12)]) == [(0, 1), (4, 6)]


def test_outline_of_single_pixel_is_a_plus():
    assert outline({5: [(5, 5)]}, {5: [(5, 5)]}) == {4: [(5, 5)], 5: [(4, 4), (6, 6)], 6: [(5, 5)]}


def test_ascii_art_groups_runs_per_character():
    art = ascii_art(10, 20, ["aab.a", " b"], {"a": "#000000", "b": "#ffffff"})

    assert art == {"a": {20: [(10, 11), (14, 14)]}, "b": {20: [(12, 12)], 21: [(11, 11)]}}


def test_ascii_art_names_first_unknown_character():
    with pytest.raises(ValueError, match="row 1, column 3: 'é' is not in the legend"):
        ascii_art(0, 0, ["aaé"], {"a": "#000000"})


def test_isometric_box_faces_cover_box_rows_once():
    top, left, right = isometric_box(0, 0, 5, 3, 7)
    box = union(top, left, right)

    assert sorted(box) == list(range(5 + 3 + 7))
    assert all(len(spans) == 1 for spans in box.values())
    assert sum(
        r - l + 1 for face in (top, left, right) for s in face.values() for l, r in s
    ) == sum(r - l + 1 for s in box.values() for l, r in s)
    assert min(s[0][0] for s in box.values()) == -6
    assert max(s[0][1] for s in box.values()) == 9
