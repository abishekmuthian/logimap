"""Mouse macros: parsing, device capabilities, event routing, and capture."""

import errno
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from logimap.config import Config
from logimap.gui.shortcut_capture import (
    ShortcutCapture, _normalize, _normalize_mouse,
)
from logimap.inject import uinput
from logimap.inject._keycodes import KEY_CODE, MOD_CODE, MOUSE_CODE
from logimap.inject._parse import ParsedShortcut, parse_shortcut, parse_shortcut_sequence
from logimap.inject.wtype import WtypeInjector
from logimap.inject.xdotool import XdotoolInjector
from logimap.inject.ydotool import YdotoolInjector
from logimap.profiles import KeyBinding, Profile


@pytest.mark.parametrize("name,code", [
    ("mouse_left", 0x110), ("mouse_right", 0x111),
    ("mouse_middle", 0x112), ("mouse_back", 0x113),
    ("mouse_forward", 0x114),
])
def test_mouse_button_events(name, code):
    assert MOUSE_CODE[name] == code
    assert uinput._events_for(parse_shortcut(name)) == [
        (uinput.EV_KEY, code, 1), (uinput.EV_SYN, 0, 0),
        (uinput.EV_KEY, code, 0), (uinput.EV_SYN, 0, 0),
    ]


@pytest.mark.parametrize("alias,name", [
    ("mouse1", "mouse_left"), ("mouse2", "mouse_right"),
    ("mouse3", "mouse_middle"), ("mouse4", "mouse_back"),
    ("mouse5", "mouse_forward"),
])
def test_numbered_alias_with_modifiers(alias, name):
    assert parse_shortcut("Ctrl+Shift+" + alias.upper()) == ParsedShortcut(
        ("ctrl", "shift"), name
    )


def test_mixed_sequence_and_modifier_release_order():
    chords = parse_shortcut_sequence("1, ctrl+shift+mouse_right, 2")
    assert [c.key for c in chords] == ["1", "mouse_right", "2"]
    events = [e for e in uinput._events_for(chords[1]) if e[0] == uinput.EV_KEY]
    assert events == [
        (uinput.EV_KEY, MOD_CODE["ctrl"], 1),
        (uinput.EV_KEY, MOD_CODE["shift"], 1),
        (uinput.EV_KEY, MOUSE_CODE["mouse_right"], 1),
        (uinput.EV_KEY, MOUSE_CODE["mouse_right"], 0),
        (uinput.EV_KEY, MOD_CODE["shift"], 0),
        (uinput.EV_KEY, MOD_CODE["ctrl"], 0),
    ]


@pytest.fixture
def virtual_input(monkeypatch):
    opens = Mock(side_effect=[10, 11])
    ioctl = Mock()
    closes = Mock()
    writes = Mock()
    sleeps = Mock()
    monkeypatch.setattr(uinput.os, "open", opens)
    monkeypatch.setattr(uinput.os, "close", closes)
    monkeypatch.setattr(uinput.os, "write", writes)
    monkeypatch.setattr(uinput.fcntl, "ioctl", ioctl)
    monkeypatch.setattr(uinput.time, "sleep", sleeps)
    monkeypatch.setattr(uinput.atexit, "register", Mock())
    injector = uinput.UinputInjector()
    sleeps.reset_mock()
    return SimpleNamespace(
        injector=injector, ioctl=ioctl, closes=closes, writes=writes,
        sleeps=sleeps, opens=opens,
    )


def decoded_events(writes):
    return [
        (call.args[0], *struct.unpack(uinput._EVENT_FMT, call.args[1])[2:])
        for call in writes.call_args_list
    ]


def test_keyboard_and_mouse_are_registered_separately(virtual_input):
    calls = [c.args for c in virtual_input.ioctl.call_args_list]
    assert (10, uinput.UI_SET_KEYBIT, MOD_CODE["ctrl"]) in calls
    assert (10, uinput.UI_SET_KEYBIT, MOUSE_CODE["mouse_left"]) not in calls
    for code in MOUSE_CODE.values():
        assert (11, uinput.UI_SET_KEYBIT, code) in calls
    assert (11, uinput.UI_SET_EVBIT, uinput.EV_REL) in calls
    assert (11, uinput.UI_SET_RELBIT, uinput.REL_X) in calls
    assert (11, uinput.UI_SET_RELBIT, uinput.REL_Y) in calls
    for fd, name in [(10, b"logimap virtual keyboard"), (11, b"logimap virtual mouse")]:
        setup = next(c[2] for c in calls if c[:2] == (fd, uinput.UI_DEV_SETUP))
        assert struct.unpack(uinput._SETUP_FMT, setup)[4].rstrip(b"\0") == name
        assert (fd, uinput.UI_DEV_CREATE) in calls


def test_click_routes_modifiers_to_keyboard_and_syns_to_correct_device(virtual_input):
    v = virtual_input
    v.injector.press("ctrl+mouse_right")
    assert decoded_events(v.writes) == [
        (10, uinput.EV_KEY, MOD_CODE["ctrl"], 1), (10, uinput.EV_SYN, 0, 0),
        (11, uinput.EV_KEY, 0x111, 1), (11, uinput.EV_SYN, 0, 0),
        (11, uinput.EV_KEY, 0x111, 0), (11, uinput.EV_SYN, 0, 0),
        (10, uinput.EV_KEY, MOD_CODE["ctrl"], 0), (10, uinput.EV_SYN, 0, 0),
    ]
    v.sleeps.assert_called_once_with(0.05)


def test_mixed_macro_and_repeated_clicks(virtual_input):
    v = virtual_input
    v.injector.press("1,mouse_left,mouse_left,2")
    key_events = [e for e in decoded_events(v.writes) if e[1] == uinput.EV_KEY]
    assert key_events == [
        (10, uinput.EV_KEY, KEY_CODE["1"], 1),
        (10, uinput.EV_KEY, KEY_CODE["1"], 0),
        (11, uinput.EV_KEY, 0x110, 1), (11, uinput.EV_KEY, 0x110, 0),
        (11, uinput.EV_KEY, 0x110, 1), (11, uinput.EV_KEY, 0x110, 0),
        (10, uinput.EV_KEY, KEY_CODE["2"], 1),
        (10, uinput.EV_KEY, KEY_CODE["2"], 0),
    ]
    assert [c.args for c in v.sleeps.call_args_list] == [(0.05,)] * 7


def test_click_waits_after_press_syn_before_release(virtual_input):
    v = virtual_input
    events_at_sleep = []
    v.sleeps.side_effect = lambda _: events_at_sleep.append(decoded_events(v.writes))
    v.injector.press("mouse_left")
    assert events_at_sleep == [[
        (11, uinput.EV_KEY, 0x110, 1), (11, uinput.EV_SYN, 0, 0),
    ]]


def test_keyboard_only_macro_keeps_existing_timing(virtual_input):
    v = virtual_input
    v.injector.press("ctrl+t,alt+f4")
    assert all(e[0] == 10 for e in decoded_events(v.writes))
    v.sleeps.assert_called_once_with(0.05)


def test_invalid_later_key_does_not_run_partial_macro(virtual_input):
    with pytest.raises(ValueError, match="no keycode"):
        virtual_input.injector.press("mouse_left,unknown_key")
    virtual_input.writes.assert_not_called()


def test_failure_releases_button_and_modifiers(virtual_input):
    v = virtual_input
    v.sleeps.side_effect = OSError(errno.EIO, "interrupted hold")
    with pytest.raises(OSError):
        v.injector.press("ctrl+shift+mouse_left")
    events = decoded_events(v.writes)
    assert events[-6:] == [
        (11, uinput.EV_KEY, 0x110, 0), (11, uinput.EV_SYN, 0, 0),
        (10, uinput.EV_KEY, MOD_CODE["shift"], 0), (10, uinput.EV_SYN, 0, 0),
        (10, uinput.EV_KEY, MOD_CODE["ctrl"], 0), (10, uinput.EV_SYN, 0, 0),
    ]


def test_close_destroys_both_devices_once(virtual_input):
    v = virtual_input
    v.injector.close()
    v.injector.close()
    assert [c.args for c in v.closes.call_args_list] == [(11,), (10,)]
    for fd in [10, 11]:
        assert sum(c.args == (fd, uinput.UI_DEV_DESTROY)
                   for c in v.ioctl.call_args_list) == 1
    with pytest.raises(RuntimeError, match="not open"):
        v.injector.press("mouse_left")


def test_mouse_init_failure_cleans_up_keyboard(monkeypatch):
    opens = Mock(side_effect=[10, 11])
    closes = Mock()
    ioctl = Mock()
    def fail_mouse(fd, request, *args):
        if fd == 11 and request == uinput.UI_DEV_CREATE:
            raise OSError(errno.EIO, "mouse unavailable")
    ioctl.side_effect = fail_mouse
    monkeypatch.setattr(uinput.os, "open", opens)
    monkeypatch.setattr(uinput.os, "close", closes)
    monkeypatch.setattr(uinput.fcntl, "ioctl", ioctl)
    monkeypatch.setattr(uinput.time, "sleep", Mock())
    with pytest.raises(OSError, match="mouse unavailable"):
        uinput.UinputInjector()
    assert [c.args for c in closes.call_args_list] == [(11,), (10,)]
    assert any(c.args == (10, uinput.UI_DEV_DESTROY) for c in ioctl.call_args_list)


@pytest.mark.parametrize("backend", [WtypeInjector, YdotoolInjector, XdotoolInjector])
def test_keyboard_fallback_rejects_entire_mouse_macro(monkeypatch, backend):
    run = Mock()
    monkeypatch.setattr("subprocess.run", run)
    with pytest.raises(ValueError, match="mouse buttons.*require.*uinput"):
        backend().press("ctrl+t,mouse1")
    run.assert_not_called()


@pytest.mark.parametrize("button,name", [
    (1, "mouse_left"), (2, "mouse_middle"), (3, "mouse_right"),
    (8, "mouse_back"), (9, "mouse_forward"),
])
def test_capture_mouse_with_modifiers(button, name):
    event = SimpleNamespace(num=button, state=0x0001 | 0x0004)
    assert _normalize_mouse(event) == "ctrl+shift+" + name


@pytest.mark.parametrize("button", [4, 5, 6, 7])
def test_capture_does_not_treat_wheel_as_side_button(button):
    assert _normalize_mouse(SimpleNamespace(num=button, state=0)) is None


def test_keyboard_capture_ignores_mouse_button_state():
    event = SimpleNamespace(keysym="T", state=0x0100 | 0x0004)
    assert _normalize(event) == "ctrl+t"


def test_capture_finish_updates_binding_once_and_removes_handlers():
    # Exercise widget callbacks without needing a window server.
    widget = object.__new__(ShortcutCapture)
    widget._capturing = True
    widget._capture_value = "ctrl+t"
    widget._value = Mock()
    widget._btn = Mock()
    widget._entry = Mock()
    widget._on_change = Mock()
    widget._suppress_trace = False
    result = widget._on_mouse(SimpleNamespace(num=3, state=0x0004))
    assert result == "break"
    assert not widget._capturing
    assert widget._value.set.call_args.args == ("ctrl+mouse_right",)
    widget._on_change.assert_called_once_with("ctrl+mouse_right")
    assert [c.args for c in widget._entry.unbind.call_args_list] == [
        ("<Key>",), ("<ButtonPress>",), ("<FocusOut>",),
    ]


def test_loading_binding_cancels_pending_capture_without_saving_placeholder():
    widget = object.__new__(ShortcutCapture)
    widget._capturing = True
    widget._capture_value = "ctrl+t"
    widget._value = Mock()
    widget._btn = Mock()
    widget._entry = Mock()
    widget._on_change = Mock()
    widget._suppress_trace = False
    widget.set("mouse_back")
    assert not widget._capturing
    assert widget._value.set.call_args.args == ("mouse_back",)
    widget._on_change.assert_not_called()


def test_mouse_macro_config_roundtrip(tmp_path):
    path = tmp_path / "profiles.json"
    config = Config(path=path)
    config.profiles["game"] = Profile(
        name="game", keys={"GRID_0": KeyBinding("Attack", "1,shift+mouse_left,2")}
    )
    config.save()
    assert Config.load(path).profiles["game"].keys["GRID_0"].shortcut == "1,shift+mouse_left,2"


@pytest.mark.parametrize("shortcut,keys", [
    ("s+w+mouse_right", ("s", "w", "mouse_right")),
    ("mouse_right+s+w", ("mouse_right", "s", "w")),
    ("ctrl+s+w+mouse2", ("s", "w", "mouse_right")),
])
def test_simultaneous_chord_parsing(shortcut, keys):
    chord = parse_shortcut(shortcut)
    assert chord.keys == keys
    assert parse_shortcut(str(chord)) == chord


@pytest.mark.parametrize("shortcut,codes", [
    ("s+w+mouse_right", [(10, KEY_CODE["s"]), (10, KEY_CODE["w"]), (11, 0x111)]),
    ("mouse_right+s+w", [(11, 0x111), (10, KEY_CODE["s"]), (10, KEY_CODE["w"])]),
    ("s+w", [(10, KEY_CODE["s"]), (10, KEY_CODE["w"])]),
])
def test_simultaneous_chord_holds_every_key_before_releasing(virtual_input, shortcut, codes):
    v = virtual_input
    events_at_sleep = []
    v.sleeps.side_effect = lambda _: events_at_sleep.append(decoded_events(v.writes))
    v.injector.press(shortcut)
    pressed = [(fd, uinput.EV_KEY, code, 1) for fd, code in codes]
    released = [(fd, uinput.EV_KEY, code, 0) for fd, code in reversed(codes)]
    assert [e for e in decoded_events(v.writes) if e[1] == uinput.EV_KEY] == pressed + released
    assert len(events_at_sleep) == 1
    assert [e for e in events_at_sleep[0] if e[1] == uinput.EV_KEY] == pressed
    assert events_at_sleep[0][-1][1] == uinput.EV_SYN


@pytest.mark.parametrize("shortcut", ["s+s", "return+enter", "mouse1+mouse_left"])
def test_duplicate_codes_pressed_and_released_only_once(virtual_input, shortcut):
    v = virtual_input
    v.injector.press(shortcut)
    events = [e for e in decoded_events(v.writes) if e[1] == uinput.EV_KEY]
    assert len(events) == 2
    assert events[0][:-1] == events[1][:-1]
    assert [e[-1] for e in events] == [1, 0]


@pytest.mark.parametrize("backend", [WtypeInjector, YdotoolInjector, XdotoolInjector])
def test_fallback_rejects_multi_key_chord_before_macro_starts(monkeypatch, backend):
    run = Mock()
    monkeypatch.setattr("subprocess.run", run)
    with pytest.raises(ValueError, match="multi-key chords require"):
        backend().press("ctrl+t,s+w")
    run.assert_not_called()
