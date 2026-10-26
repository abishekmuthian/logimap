"""Shortcut injection — probe order: uinput → wtype → ydotool → xdotool.

uinput is the primary path on Linux: it bypasses the compositor entirely and
keeps logimap in sole control of the keystroke pipeline (no third-party
daemon, no socket). It needs the user to be able to open /dev/uinput rw —
see README for the udev rule.

wtype works only on compositors that expose `zwp_virtual_keyboard_v1` to
non-IME clients (sway, wlroots — *not* KWin 6).

ydotool is kept as a fallback for users who already have ydotoold running;
it's unmaintained and not recommended for new setups.

xdotool is XWayland-only and rarely useful on a modern Plasma session.

Multi-chord shortcuts (e.g. tmux prefix sequences) are expressed with commas:
    press("ctrl+b,shift+'")
Mouse clicks use mouse_left/right/middle/back/forward in the built-in uinput
backend and can be mixed with keyboard chords (e.g. "1,mouse_left,2").
Each chord is injected with a 50 ms gap so the receiving application can
distinguish the chords.  Single chords like "ctrl+t" work unchanged.
With uinput, "mouse_right@500" holds for 500 ms and "a,wait:300,b" replaces
the default gap with a 300 ms pause. Other backends reject timed macros.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Protocol

log = logging.getLogger(__name__)


class Injector(Protocol):
    def press(self, shortcut: str) -> None: ...


def _can_open_uinput() -> bool:
    try:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    os.close(fd)
    return True


def _wtype_works() -> bool:
    """True iff `wtype` can bind to virtual_keyboard_v1 on this compositor.

    wtype with an empty string is a no-op that still goes through the
    compositor handshake; if the protocol isn't exposed we get exit 1
    immediately.
    """
    try:
        r = subprocess.run(["wtype", ""], capture_output=True, text=True, timeout=1.5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def get_injector() -> Injector:
    if _can_open_uinput():
        try:
            from .uinput import UinputInjector
            inst = UinputInjector()
            log.info("using built-in uinput injector")
            return inst
        except OSError as e:
            log.warning("uinput injector init failed (%s) — trying alternatives", e)
    else:
        log.debug("/dev/uinput not writable for current user — skipping uinput")

    if shutil.which("wtype") and _wtype_works():
        from .wtype import WtypeInjector
        log.info("using wtype for shortcut injection")
        return WtypeInjector()

    if shutil.which("ydotool"):
        from .ydotool import YdotoolInjector
        log.warning("falling back to ydotool — consider installing the uinput udev rule instead")
        return YdotoolInjector()

    if shutil.which("xdotool"):
        from .xdotool import XdotoolInjector
        log.warning("falling back to xdotool (XWayland-only)")
        return XdotoolInjector()

    raise RuntimeError(
        "No usable keystroke injector found. Either:\n"
        "  - grant /dev/uinput access to your user (recommended; see README), or\n"
        "  - install wtype / ydotool / xdotool"
    )
