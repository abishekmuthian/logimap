"""Timed macro syntax and event timing without hardware or real sleeps."""

import errno
from unittest.mock import Mock

import pytest

from logimap.config import Config
from logimap.inject import uinput
from logimap.inject._keycodes import KEY_CODE, MOD_CODE, MOUSE_CODE
from logimap.inject._parse import (
    ParsedShortcut, ParsedWait, ShortcutParseError,
    parse_shortcut, parse_shortcut_sequence,
)
from logimap.inject.wtype import WtypeInjector
from logimap.inject.xdotool import XdotoolInjector
from logimap.inject.ydotool import YdotoolInjector
from logimap.profiles import KeyBinding, Profile

from .test_mouse_macros import decoded_events, virtual_input


@pytest.mark.parametrize("text,expected", [
    ("mouse2@500", ParsedShortcut((), "mouse_right", hold_ms=500)),
    (" Ctrl+W+Mouse_Right @ 750 ", ParsedShortcut(
        ("ctrl",), "mouse_right", ("w",), hold_ms=750)),
    ("a@0", ParsedShortcut((), "a", hold_ms=0)),
    ("a@60000", ParsedShortcut((), "a", hold_ms=60000)),
    ("@@250", ParsedShortcut(("shift",), "2", hold_ms=250)),
    ("ctrl+@@250", ParsedShortcut(("ctrl", "shift"), "2", hold_ms=250)),
])
def test_parse_hold_and_roundtrip(text, expected):
    parsed = parse_shortcut(text)
    assert parsed == expected
    assert parse_shortcut(str(parsed)) == expected


@pytest.mark.parametrize("text", ["@", "ctrl+@", "shift+@"])
def test_at_key_remains_backward_compatible(text):
    parsed = parse_shortcut(text)
    assert parsed.key == "2"
    assert "shift" in parsed.modifiers
    assert parsed.hold_ms is None


@pytest.mark.parametrize("text", ["@+a", "ctrl+@+a", "@+mouse_left"])
def test_at_key_in_held_chord_remains_backward_compatible(text):
    parsed = parse_shortcut(text)
    assert "2" in parsed.held_keys
    assert "shift" in parsed.modifiers
    assert parsed.hold_ms is None
    assert parse_shortcut(str(parsed)) == parsed


def test_parse_mixed_steps_and_wait_roundtrip():
    steps = parse_shortcut_sequence("a@200, WAIT: 300 ,ctrl+mouse1@500")
    assert steps == [
        ParsedShortcut((), "a", hold_ms=200), ParsedWait(300),
        ParsedShortcut(("ctrl",), "mouse_left", hold_ms=500),
    ]
    assert parse_shortcut_sequence(",".join(map(str, steps))) == steps
    assert parse_shortcut_sequence("wait:0") == [ParsedWait(0)]


@pytest.mark.parametrize("duration", [
    "", "-1", "+1", "1.5", "nan", "inf", "1e3", "60001",
    "99999999999999999999999", "500ms", "٥٠٠",
])
@pytest.mark.parametrize("template", ["a,mouse_left@{}", "mouse_left,wait:{}"])
def test_invalid_duration_rejected_before_any_events(virtual_input, duration, template):
    with pytest.raises(ShortcutParseError, match="duration"):
        virtual_input.injector.press(template.format(duration))
    virtual_input.writes.assert_not_called()
    virtual_input.sleeps.assert_not_called()


@pytest.mark.parametrize("text", ["@500", "ctrl+@500"])
def test_duration_without_key_rejected(text):
    with pytest.raises(ShortcutParseError):
        parse_shortcut(text)


def test_hold_spans_all_inputs_and_releases_in_reverse(virtual_input):
    v = virtual_input
    during_hold = []
    v.sleeps.side_effect = lambda _: during_hold.append(decoded_events(v.writes))
    v.injector.press("ctrl+w+mouse_right@500")
    v.sleeps.assert_called_once_with(0.5)
    codes = [(10, MOD_CODE["ctrl"]), (10, KEY_CODE["w"]), (11, MOUSE_CODE["mouse_right"])]
    assert [e for e in during_hold[0] if e[1] == uinput.EV_KEY] == [
        (fd, uinput.EV_KEY, code, 1) for fd, code in codes
    ]
    assert during_hold[0][-1] == (11, uinput.EV_SYN, 0, 0)
    assert [e for e in decoded_events(v.writes) if e[1] == uinput.EV_KEY][-3:] == [
        (fd, uinput.EV_KEY, code, 0) for fd, code in reversed(codes)
    ]


@pytest.mark.parametrize("text,sleeps", [
    ("mouse_right,wait:300,mouse_right", [0.05, 0.3, 0.05]),
    ("mouse_right@500,mouse_left", [0.5, 0.05, 0.05]),
    ("a@200,b", [0.2, 0.05]),
    ("mouse_left@0,wait:0,mouse_right@0", [0]),
    ("wait:100,a,wait:200,wait:300,b,wait:400", [0.1, 0.2, 0.3, 0.4]),
    ("wait:500", [0.5]),
    ("a@0,b@0", [0.05]),
])
def test_explicit_waits_replace_implicit_gaps(virtual_input, text, sleeps):
    v = virtual_input
    v.injector.press(text)
    assert [c.args[0] for c in v.sleeps.call_args_list] == sleeps


def test_pause_occurs_after_release_and_next_press_at_expected_time(virtual_input):
    v = virtual_input
    now = 0
    sleeps = []
    def advance(seconds):
        nonlocal now
        sleeps.append((now, seconds, decoded_events(v.writes)))
        now += seconds
    v.sleeps.side_effect = advance
    v.injector.press("mouse_right@500,wait:300,mouse_left@200")
    assert now == pytest.approx(1.0)
    assert sleeps[1][0:2] == (0.5, 0.3)
    assert sleeps[1][2][-2:] == [
        (11, uinput.EV_KEY, MOUSE_CODE["mouse_right"], 0),
        (11, uinput.EV_SYN, 0, 0),
    ]
    assert sleeps[2][0] == pytest.approx(0.8)
    assert sleeps[2][2][-2:] == [
        (11, uinput.EV_KEY, MOUSE_CODE["mouse_left"], 1),
        (11, uinput.EV_SYN, 0, 0),
    ]


def test_timed_chord_still_deduplicates_linux_codes(virtual_input):
    v = virtual_input
    v.injector.press("return+enter@250")
    assert len([e for e in decoded_events(v.writes) if e[1] == uinput.EV_KEY]) == 2
    v.sleeps.assert_called_once_with(0.25)


def test_unknown_later_key_rejected_before_hold_or_wait(virtual_input):
    with pytest.raises(ValueError, match="no keycode"):
        virtual_input.injector.press("a@500,wait:300,unknown_key@200")
    virtual_input.writes.assert_not_called()
    virtual_input.sleeps.assert_not_called()


def test_interrupted_explicit_hold_releases_all_inputs(virtual_input):
    v = virtual_input
    v.sleeps.side_effect = OSError(errno.EIO, "interrupted hold")
    with pytest.raises(OSError):
        v.injector.press("ctrl+w+mouse_right@500,wait:300,a")
    assert decoded_events(v.writes)[-6:] == [
        (11, uinput.EV_KEY, MOUSE_CODE["mouse_right"], 0), (11, uinput.EV_SYN, 0, 0),
        (10, uinput.EV_KEY, KEY_CODE["w"], 0), (10, uinput.EV_SYN, 0, 0),
        (10, uinput.EV_KEY, MOD_CODE["ctrl"], 0), (10, uinput.EV_SYN, 0, 0),
    ]


def test_interrupted_wait_has_no_held_inputs_or_later_events(virtual_input):
    v = virtual_input
    v.sleeps.side_effect = [None, OSError(errno.EIO, "interrupted wait")]
    with pytest.raises(OSError):
        v.injector.press("mouse_right,wait:300,mouse_left")
    assert decoded_events(v.writes) == [
        (11, uinput.EV_KEY, MOUSE_CODE["mouse_right"], 1), (11, uinput.EV_SYN, 0, 0),
        (11, uinput.EV_KEY, MOUSE_CODE["mouse_right"], 0), (11, uinput.EV_SYN, 0, 0),
    ]


@pytest.mark.parametrize("backend", [WtypeInjector, YdotoolInjector, XdotoolInjector])
@pytest.mark.parametrize("text", ["ctrl+t,a@500", "ctrl+t,wait:300,a", "wait:0", "a@0"])
def test_fallbacks_reject_entire_timed_macro(monkeypatch, backend, text):
    run = Mock()
    monkeypatch.setattr("subprocess.run", run)
    with pytest.raises(ValueError, match="timed macros require.*uinput"):
        backend().press(text)
    run.assert_not_called()


def test_timing_persists_on_later_profile_page(tmp_path):
    text = "space+mouse_right@500,wait:300,mouse_left"
    config = Config(path=tmp_path / "profiles.json")
    config.profiles["game"] = Profile(
        name="game", extra_pages=[{"GRID_2": KeyBinding("Timed", text)}]
    )
    config.save()
    binding = Config.load(config.path).profiles["game"].get("GRID_2", 1)
    assert binding.shortcut == text
    assert parse_shortcut_sequence(binding.shortcut)[1] == ParsedWait(300)
