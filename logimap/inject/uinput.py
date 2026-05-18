"""Built-in uinput injector — opens /dev/uinput directly, no third-party daemon.

KWin 6 doesn't expose zwp_virtual_keyboard_v1 to non-IME clients, so wtype is
unusable on Plasma 6. Rather than depend on the unmaintained `ydotool`, we
synthesize keystrokes via the kernel's uinput interface ourselves: open
/dev/uinput, register a virtual keyboard, write EV_KEY events for the
shortcut, syn after each.

Setup needed by the user:

    # /etc/udev/rules.d/99-logimap-uinput.rules
    KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"

…then `sudo usermod -aG input $USER`, log out, log back in.
"""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
import struct
import time

from ._keycodes import KEY_CODE, MOD_CODE
from ._parse import ParsedShortcut, parse_shortcut_sequence

log = logging.getLogger(__name__)

# --- Linux uinput constants (from <linux/uinput.h>, <linux/input.h>) ---------
EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0
BUS_VIRTUAL = 0x06

# ioctl numbers, derived from _IO/_IOW with type='U' (UINPUT_IOCTL_BASE):
#   _IOW(dir=1, type='U', nr, size) = (1 << 30) | (size << 16) | ('U' << 8) | nr
UI_DEV_CREATE = 0x5501           # _IO('U', 1)
UI_DEV_DESTROY = 0x5502          # _IO('U', 2)
UI_DEV_SETUP = 0x405C5503        # _IOW('U', 3, sizeof(uinput_setup)=92)
UI_SET_EVBIT = 0x40045564        # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565       # _IOW('U', 101, int)

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# x86_64: 8+8+2+2+4 = 24 bytes. ('Q' to keep packing endian-explicit; native 'l'
# would also work on this arch but is fragile across platforms.)
_EVENT_FMT = "@llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)
assert _EVENT_SIZE == 24, _EVENT_SIZE

# struct uinput_setup {
#     struct input_id id;     // 4x __u16 = 8
#     char name[80];          // 80
#     __u32 ff_effects_max;   // 4
# } = 92 bytes
_SETUP_FMT = "@HHHH80sI"
_SETUP_SIZE = struct.calcsize(_SETUP_FMT)
assert _SETUP_SIZE == 92, _SETUP_SIZE

UINPUT_PATH = "/dev/uinput"


def _events_for(parsed: ParsedShortcut) -> list[tuple[int, int, int]]:
    """Compute the (type, code, value) sequence to fire one chord.

    Press modifiers in order, press main key, release main key, release
    modifiers in reverse. SYN_REPORT after every state change so the
    kernel coalesces and dispatches.
    """
    out: list[tuple[int, int, int]] = []
    for m in parsed.modifiers:
        out.append((EV_KEY, MOD_CODE[m], 1))
        out.append((EV_SYN, SYN_REPORT, 0))
    kc = KEY_CODE[parsed.key.lower()]
    out.append((EV_KEY, kc, 1))
    out.append((EV_SYN, SYN_REPORT, 0))
    out.append((EV_KEY, kc, 0))
    out.append((EV_SYN, SYN_REPORT, 0))
    for m in reversed(parsed.modifiers):
        out.append((EV_KEY, MOD_CODE[m], 0))
        out.append((EV_SYN, SYN_REPORT, 0))
    return out


class UinputInjector:
    def __init__(self) -> None:
        self._fd: int | None = None
        self._open()
        atexit.register(self.close)

    def _open(self) -> None:
        fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            for code in set(MOD_CODE.values()) | set(KEY_CODE.values()):
                fcntl.ioctl(fd, UI_SET_KEYBIT, code)

            setup = struct.pack(
                _SETUP_FMT,
                BUS_VIRTUAL,
                0x1209,                      # vendor: pid.codes generic
                0xCAFE,                      # product: arbitrary
                1,                           # version
                b"logimap virtual keyboard",
                0,                           # ff_effects_max
            )
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
            # Brief settle so udev/Wayland have routed the new device before
            # our first event hits the bus.
            time.sleep(0.05)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd

    def _emit(self, etype: int, code: int, value: int) -> None:
        assert self._fd is not None
        os.write(self._fd, struct.pack(_EVENT_FMT, 0, 0, etype, code, value))

    def press(self, shortcut: str) -> None:
        if self._fd is None:
            raise RuntimeError("uinput device not open")
        chords = parse_shortcut_sequence(shortcut)
        try:
            events_list = [_events_for(c) for c in chords]
        except KeyError as e:
            raise ValueError(f"uinput: no keycode for {e.args[0]!r}") from e
        for i, events in enumerate(events_list):
            if i > 0:
                time.sleep(0.05)
            for etype, code, value in events:
                self._emit(etype, code, value)

    def close(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
