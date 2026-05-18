import pytest

from logimap.inject._parse import (
    ParsedShortcut,
    ShortcutParseError,
    parse_shortcut,
    parse_shortcut_sequence,
)
from logimap.inject.wtype import _build_argv


def test_single_key():
    p = parse_shortcut("t")
    assert p == ParsedShortcut(modifiers=(), key="t")


def test_ctrl_t():
    p = parse_shortcut("ctrl+t")
    assert p.modifiers == ("ctrl",)
    assert p.key == "t"


def test_multiple_modifiers():
    p = parse_shortcut("Ctrl+Shift+T")
    assert p.modifiers == ("ctrl", "shift")
    assert p.key == "t"


def test_control_alias():
    p = parse_shortcut("control+c")
    assert p.modifiers == ("ctrl",)


def test_super_logo_alias():
    p = parse_shortcut("super+l")
    assert p.modifiers == ("logo",)


def test_function_key():
    p = parse_shortcut("alt+f4")
    assert p.modifiers == ("alt",)
    assert p.key == "f4"


def test_duplicate_modifier_deduped():
    p = parse_shortcut("ctrl+ctrl+t")
    assert p.modifiers == ("ctrl",)


def test_empty_raises():
    with pytest.raises(ShortcutParseError):
        parse_shortcut("")


def test_only_modifier_raises():
    with pytest.raises(ShortcutParseError):
        parse_shortcut("ctrl+shift")


def test_unknown_modifier_raises():
    with pytest.raises(ShortcutParseError):
        parse_shortcut("hyper+t")


def test_shifted_symbol_question_mark():
    p = parse_shortcut("ctrl+?")
    assert p.modifiers == ("ctrl", "shift")
    assert p.key == "/"


def test_shifted_symbol_with_existing_shift_not_duplicated():
    p = parse_shortcut("ctrl+shift+?")
    assert p.modifiers == ("ctrl", "shift")
    assert p.key == "/"


def test_shifted_symbol_bare():
    p = parse_shortcut("!")
    assert p.modifiers == ("shift",)
    assert p.key == "1"


def test_shifted_symbol_braces():
    p = parse_shortcut("ctrl+}")
    assert p.modifiers == ("ctrl", "shift")
    assert p.key == "]"


def test_wtype_argv_ctrl_t():
    argv = _build_argv(parse_shortcut("ctrl+t"))
    assert argv[0] == "wtype"
    assert "-M" in argv and "ctrl" in argv
    assert "-P" in argv and "-p" in argv


def test_wtype_argv_ctrl_shift_f10():
    argv = _build_argv(parse_shortcut("ctrl+shift+f10"))
    # both ctrl and shift pressed
    m_indices = [i for i, a in enumerate(argv) if a == "-M"]
    assert len(m_indices) == 2
    assert "F10" in argv
    # both released
    lower_m = [i for i, a in enumerate(argv) if a == "-m"]
    assert len(lower_m) == 2


class TestParseShortcutSequence:
    def test_single_chord_passthrough(self):
        result = parse_shortcut_sequence("ctrl+t")
        assert len(result) == 1
        assert result[0] == ParsedShortcut(modifiers=("ctrl",), key="t")

    def test_two_chord_sequence(self):
        result = parse_shortcut_sequence("ctrl+b,shift+'")
        assert len(result) == 2
        assert result[0] == ParsedShortcut(modifiers=("ctrl",), key="b")
        assert result[1] == ParsedShortcut(modifiers=("shift",), key="'")

    def test_tmux_double_quote(self):
        result = parse_shortcut_sequence('ctrl+b,"')
        assert len(result) == 2
        assert result[0] == ParsedShortcut(modifiers=("ctrl",), key="b")
        assert result[1] == ParsedShortcut(modifiers=("shift",), key="'")

    def test_three_chord_sequence(self):
        result = parse_shortcut_sequence("ctrl+b,ctrl+c,ctrl+d")
        assert len(result) == 3
        assert result[0].key == "b"
        assert result[1].key == "c"
        assert result[2].key == "d"

    def test_whitespace_around_comma(self):
        result = parse_shortcut_sequence("ctrl+b , shift+'")
        assert len(result) == 2
        assert result[0] == ParsedShortcut(modifiers=("ctrl",), key="b")
        assert result[1] == ParsedShortcut(modifiers=("shift",), key="'")

    def test_empty_chord_in_sequence_raises(self):
        with pytest.raises(ShortcutParseError, match="empty chord"):
            parse_shortcut_sequence("ctrl+b,,shift+'")

    def test_trailing_comma_raises(self):
        with pytest.raises(ShortcutParseError, match="empty chord"):
            parse_shortcut_sequence("ctrl+b,")

    def test_leading_comma_raises(self):
        with pytest.raises(ShortcutParseError, match="empty chord"):
            parse_shortcut_sequence(",ctrl+b")

    def test_bare_key_as_sequence(self):
        result = parse_shortcut_sequence("t")
        assert result == [ParsedShortcut(modifiers=(), key="t")]

    def test_shifted_symbol_in_second_chord(self):
        result = parse_shortcut_sequence("ctrl+b,?")
        assert len(result) == 2
        assert result[0] == ParsedShortcut(modifiers=("ctrl",), key="b")
        assert result[1] == ParsedShortcut(modifiers=("shift",), key="/")
