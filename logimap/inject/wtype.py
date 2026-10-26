"""Wayland shortcut injector via `wtype` (virtual keyboard protocol)."""

from __future__ import annotations

import logging
import subprocess

import time

from ._keycodes import MOUSE_CODE
from ._parse import ParsedShortcut, ParsedWait, parse_shortcut, parse_shortcut_sequence

log = logging.getLogger(__name__)

_WTYPE_MOD = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "logo": "logo",
}

_KEY_ALIAS = {
    "return": "Return",
    "enter": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "insert": "Insert",
    "menu": "Menu",
}


def _map_key(key: str) -> str:
    lower = key.lower()
    if lower in _KEY_ALIAS:
        return _KEY_ALIAS[lower]
    if lower.startswith("f") and lower[1:].isdigit():
        return "F" + lower[1:]
    if len(key) == 1:
        return key
    return key


def _build_argv(parsed: ParsedShortcut) -> list[str]:
    argv = ["wtype"]
    for m in parsed.modifiers:
        argv += ["-M", _WTYPE_MOD[m]]
    keycap = _map_key(parsed.key)
    argv += ["-P", keycap, "-p", keycap]
    for m in reversed(parsed.modifiers):
        argv += ["-m", _WTYPE_MOD[m]]
    return argv


class WtypeInjector:
    def press(self, shortcut: str) -> None:
        chords = parse_shortcut_sequence(shortcut)
        if any(isinstance(c, ParsedWait) or c.hold_ms is not None for c in chords):
            raise ValueError("wtype: timed macros require the built-in uinput injector")
        if any(chord.held_keys or chord.key in MOUSE_CODE for chord in chords):
            raise ValueError(
                "wtype: mouse buttons and multi-key chords require the built-in uinput injector; "
                "grant /dev/uinput access (see README)"
            )
        for i, parsed in enumerate(chords):
            if i > 0:
                time.sleep(0.05)
            argv = _build_argv(parsed)
            log.debug("wtype argv: %s", argv)
            try:
                r = subprocess.run(argv, check=False, timeout=2.0, capture_output=True, text=True)
            except FileNotFoundError:
                log.error("wtype not installed — run: sudo dnf install wtype")
                raise
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "").strip()
                log.error("wtype failed for %s: exit %s — %s", shortcut, r.returncode, msg)
                raise RuntimeError(f"wtype exit {r.returncode}: {msg}")
