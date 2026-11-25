from aseprite_mcp.filenames import safe_stem, unique_stems


def test_safe_stem_replaces_forbidden_characters():
    assert safe_stem('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_safe_stem_replaces_control_characters():
    assert safe_stem("tab\there\x7f") == "tab_here_"


def test_safe_stem_drops_trailing_dots_and_spaces():
    assert safe_stem("hat. . ") == "hat"


def test_safe_stem_hides_no_file_behind_a_leading_dot():
    assert safe_stem(".hidden") == "_hidden"


def test_safe_stem_prefixes_reserved_windows_names():
    assert safe_stem("con") == "_con"
    assert safe_stem("COM1") == "_COM1"
    assert safe_stem("nul.txt") == "_nul.txt"
    assert safe_stem("console") == "console"


def test_safe_stem_of_nothing_usable():
    assert safe_stem("...") == "layer"
    assert safe_stem("") == "layer"


def test_safe_stem_limits_length_in_bytes():
    stem = safe_stem("é" * 200)
    assert len(stem.encode("utf-8")) <= 100
    assert stem == "é" * 50


def test_safe_stem_keeps_unicode():
    assert safe_stem("tête") == "tête"


def test_unique_stems_number_repeats():
    assert unique_stems(["a", "b", "a", "a"]) == ["a", "b", "a_2", "a_3"]


def test_unique_stems_ignore_case():
    assert unique_stems(["Hat", "hat"]) == ["Hat", "hat_2"]


def test_unique_stems_skip_a_suffix_already_taken():
    assert unique_stems(["a_2", "a", "a"]) == ["a_2", "a", "a_3"]


def test_unique_stems_leave_a_later_name_to_its_owner():
    assert unique_stems(["a", "a", "a_2"]) == ["a", "a_3", "a_2"]


def test_safe_stem_prefixes_console_and_superscript_device_names():
    assert safe_stem("CONIN$") == "_CONIN$"
    assert safe_stem("conout$") == "_conout$"
    assert safe_stem("COM¹") == "_COM¹"
    assert safe_stem("lpt³.txt") == "_lpt³.txt"
    assert safe_stem("COM0") == "COM0"
