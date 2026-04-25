"""Fallback X11/XWayland injector via `xdotool`."""

from __future__ import annotations

import logging
import subprocess

from ._parse import parse_shortcut

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
        parsed = parse_shortcut(shortcut)
        argv = ["xdotool", "key", "--clearmodifiers", _xdo_keysym(parsed)]
        log.debug("xdotool argv: %s", argv)
        subprocess.run(argv, check=True, timeout=2.0)
