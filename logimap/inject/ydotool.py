"""ydotool injector — fallback for users who already have ydotoold running.

Prefer the built-in uinput injector instead; ydotool is unmaintained and
adds a third-party root daemon to the trust boundary.
"""

from __future__ import annotations

import logging
import subprocess

import time

from ._keycodes import KEY_CODE, MOD_CODE
from ._parse import parse_shortcut_sequence

log = logging.getLogger(__name__)


def _build_argv(parsed: ParsedShortcut) -> list[str]:
    codes: list[str] = []
    for m in parsed.modifiers:
        codes.append(f"{MOD_CODE[m]}:1")
    try:
        kc = KEY_CODE[parsed.key.lower()]
    except KeyError as e:
        raise ValueError(f"ydotool: no keycode for {parsed.key!r}") from e
    codes.append(f"{kc}:1")
    codes.append(f"{kc}:0")
    for m in reversed(parsed.modifiers):
        codes.append(f"{MOD_CODE[m]}:0")
    return ["ydotool", "key", *codes]


class YdotoolInjector:
    def press(self, shortcut: str) -> None:
        chords = parse_shortcut_sequence(shortcut)
        for i, parsed in enumerate(chords):
            if i > 0:
                time.sleep(0.05)
            argv = _build_argv(parsed)
            log.debug("ydotool argv: %s", argv)
            try:
                r = subprocess.run(argv, check=False, timeout=2.0, capture_output=True, text=True)
            except FileNotFoundError:
                log.error("ydotool not installed")
                raise
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "").strip()
                log.error("ydotool failed for %s: exit %s — %s", shortcut, r.returncode, msg)
                raise RuntimeError(f"ydotool exit {r.returncode}: {msg}")
