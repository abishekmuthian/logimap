"""Fallback X11/XWayland injector via `xdotool`."""

from __future__ import annotations

import logging
import subprocess

import time

from ._keycodes import MOUSE_CODE
from ._parse import ParsedWait, parse_shortcut_sequence

log = logging.getLogger(__name__)

_XDO_MOD = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "logo": "super",
}


def _xdo_keysym(parsed) -> str:
    parts = [_XDO_MOD[m] for m in parsed.modifiers]
    key = parsed.key
    if len(key) == 1:
        parts.append(key)
    elif key.startswith("f") and key[1:].isdigit():
        parts.append("F" + key[1:])
    else:
        parts.append(key.capitalize())
    return "+".join(parts)


class XdotoolInjector:
    def press(self, shortcut: str) -> None:
        chords = parse_shortcut_sequence(shortcut)
        if any(isinstance(c, ParsedWait) or c.hold_ms is not None for c in chords):
            raise ValueError("xdotool: timed macros require the built-in uinput injector")
        if any(chord.held_keys or chord.key in MOUSE_CODE for chord in chords):
            raise ValueError(
                "xdotool: mouse buttons and multi-key chords require the built-in uinput injector; "
                "grant /dev/uinput access (see README)"
            )
        for i, parsed in enumerate(chords):
            if i > 0:
                time.sleep(0.05)
            argv = ["xdotool", "key", "--clearmodifiers", _xdo_keysym(parsed)]
            log.debug("xdotool argv: %s", argv)
            subprocess.run(argv, check=True, timeout=2.0)
