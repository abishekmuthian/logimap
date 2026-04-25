"""Pure-logic tests for the uinput injector.

Doesn't touch /dev/uinput — only checks the event sequence and packed-event
size match the kernel ABI.
"""

from __future__ import annotations

import struct

from logimap.inject._keycodes import KEY_CODE, MOD_CODE
from logimap.inject._parse import parse_shortcut
from logimap.inject.uinput import (
    EV_KEY,
    EV_SYN,
    SYN_REPORT,
    _EVENT_FMT,
    _EVENT_SIZE,
    _SETUP_FMT,
    _SETUP_SIZE,
    _events_for,
)


def test_event_struct_size_matches_kernel_abi():
    assert _EVENT_SIZE == 24, "input_event must be 24 bytes on x86_64"
    assert _SETUP_SIZE == 92, "uinput_setup must be 92 bytes"


def test_ctrl_t_emits_press_release_with_syns():
    parsed = parse_shortcut("ctrl+t")
    events = _events_for(parsed)

    # ctrl down, syn, t down, syn, t up, syn, ctrl up, syn = 8 events
    assert len(events) == 8

    ctrl = MOD_CODE["ctrl"]
    t = KEY_CODE["t"]
    assert events == [
        (EV_KEY, ctrl, 1), (EV_SYN, SYN_REPORT, 0),
        (EV_KEY, t, 1),    (EV_SYN, SYN_REPORT, 0),
        (EV_KEY, t, 0),    (EV_SYN, SYN_REPORT, 0),
        (EV_KEY, ctrl, 0), (EV_SYN, SYN_REPORT, 0),
    ]


def test_ctrl_shift_t_releases_modifiers_in_reverse():
    parsed = parse_shortcut("ctrl+shift+t")
    events = _events_for(parsed)
    # 3 presses + 3 releases + 6 syns = 12
    assert len(events) == 12
    # last two non-syn events: shift up, then ctrl up
    key_events = [e for e in events if e[0] == EV_KEY]
    assert key_events[-2:] == [
        (EV_KEY, MOD_CODE["shift"], 0),
        (EV_KEY, MOD_CODE["ctrl"], 0),
    ]


def test_packed_event_round_trips():
    buf = struct.pack(_EVENT_FMT, 0, 0, EV_KEY, KEY_CODE["t"], 1)
    assert len(buf) == 24
    sec, usec, etype, code, value = struct.unpack(_EVENT_FMT, buf)
    assert (etype, code, value) == (EV_KEY, KEY_CODE["t"], 1)
