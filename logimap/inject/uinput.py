"""Built-in uinput injector — opens /dev/uinput directly, no third-party daemon.

KWin 6 doesn't expose zwp_virtual_keyboard_v1 to non-IME clients, so wtype is
unusable on Plasma 6. Rather than depend on the unmaintained `ydotool`, we
synthesize keystrokes via the kernel's uinput interface ourselves: open
/dev/uinput, register separate virtual keyboard and mouse devices, write
EV_KEY events for each chord, syn after each.

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

from ._keycodes import KEY_CODE, MOD_CODE, MOUSE_CODE
from ._parse import ParsedShortcut, ParsedWait, parse_shortcut_sequence

log = logging.getLogger(__name__)

# --- Linux uinput constants (from <linux/uinput.h>, <linux/input.h>) ---------
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
REL_X = 0x00
REL_Y = 0x01
CLICK_HOLD_SECONDS = 0.05
SYN_REPORT = 0
BUS_VIRTUAL = 0x06

# ioctl numbers, derived from _IO/_IOW with type='U' (UINPUT_IOCTL_BASE):
#   _IOW(dir=1, type='U', nr, size) = (1 << 30) | (size << 16) | ('U' << 8) | nr
UI_DEV_CREATE = 0x5501           # _IO('U', 1)
UI_DEV_DESTROY = 0x5502          # _IO('U', 2)
UI_DEV_SETUP = 0x405C5503        # _IOW('U', 3, sizeof(uinput_setup)=92)
UI_SET_EVBIT = 0x40045564        # _IOW('U', 100, int)
UI_SET_KEYBIT = 0x40045565       # _IOW('U', 101, int)
UI_SET_RELBIT = 0x40045566       # _IOW('U', 102, int)

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

    Press modifiers, then all keys/buttons; release in reverse order.
    SYN_REPORT after every state change so the kernel dispatches each one.
    """
    codes = [MOD_CODE[m] for m in parsed.modifiers]
    for key in parsed.keys:
        table = MOUSE_CODE if key in MOUSE_CODE else KEY_CODE
        codes.append(table[key.lower()])
    # Aliases (e.g. return+enter) must not press/release the same code twice.
    codes = list(dict.fromkeys(codes))
    out: list[tuple[int, int, int]] = []
    for code in codes:
        out.extend(((EV_KEY, code, 1), (EV_SYN, SYN_REPORT, 0)))
    for code in reversed(codes):
        out.extend(((EV_KEY, code, 0), (EV_SYN, SYN_REPORT, 0)))
    return out


class UinputInjector:
    def __init__(self) -> None:
        self._fd: int | None = None
        self._mouse_fd: int | None = None
        self._fd = self._open()
        try:
            self._mouse_fd = self._open(mouse=True)
        except Exception:
            self.close()
            raise
        atexit.register(self.close)

    def _open(self, *, mouse: bool = False) -> int:
        fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            if mouse:
                # REL_X/Y and BTN_LEFT let udev/libinput classify this as a
                # pointer. No motion events are sent: clicks use the cursor.
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
                fcntl.ioctl(fd, UI_SET_RELBIT, REL_X)
                fcntl.ioctl(fd, UI_SET_RELBIT, REL_Y)
                codes = set(MOUSE_CODE.values())
            else:
                codes = set(MOD_CODE.values()) | set(KEY_CODE.values())
            for code in codes:
                fcntl.ioctl(fd, UI_SET_KEYBIT, code)

            setup = struct.pack(
                _SETUP_FMT,
                BUS_VIRTUAL,
                0x1209,                      # vendor: pid.codes generic
                0xCAFE,                      # product: arbitrary
                1,                           # version
                b"logimap virtual mouse" if mouse else b"logimap virtual keyboard",
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
        return fd

    def _emit(self, etype: int, code: int, value: int, *, mouse: bool = False) -> None:
        fd = self._mouse_fd if mouse else self._fd
        assert fd is not None
        os.write(fd, struct.pack(_EVENT_FMT, 0, 0, etype, code, value))

    def press(self, shortcut: str) -> None:
        if self._fd is None or self._mouse_fd is None:
            raise RuntimeError("uinput devices not open")
        chords = parse_shortcut_sequence(shortcut)
        try:
            events_list = [
                None if isinstance(c, ParsedWait) else _events_for(c) for c in chords
            ]
        except KeyError as e:
            raise ValueError(f"uinput: no keycode for {e.args[0]!r}") from e
        # Give every action in a game macro a hold, including single keys.
        game_macro = any(
            isinstance(c, ParsedShortcut)
            and (c.held_keys or any(k in MOUSE_CODE for k in c.keys))
            for c in chords
        )
        # Validate the entire sequence above before sending its first event.
        held: list[tuple[bool, int]] = []
        try:
            for i, (chord, events) in enumerate(zip(chords, events_list)):
                if isinstance(chord, ParsedWait):
                    # Adjacent explicit waits add together; no implicit gaps.
                    time.sleep(chord.duration_ms / 1000)
                    continue
                if i > 0 and isinstance(chords[i - 1], ParsedShortcut):
                    time.sleep(0.05)
                assert events is not None
                mouse = False
                hold_seconds = (
                    chord.hold_ms / 1000 if chord.hold_ms is not None
                    else CLICK_HOLD_SECONDS if game_macro else 0
                )
                needs_hold = hold_seconds > 0
                for etype, code, value in events:
                    if etype == EV_KEY:
                        mouse = code in MOUSE_CODE.values()
                        if value == 0 and needs_hold:
                            # All keys/buttons are down before the hold, even
                            # when a mouse button comes first in the chord.
                            time.sleep(hold_seconds)
                            needs_hold = False
                    self._emit(etype, code, value, mouse=mouse)
                    if etype == EV_KEY:
                        if value == 1:
                            held.append((mouse, code))
                        else:
                            held.remove((mouse, code))
        finally:
            # Avoid leaving modifiers/buttons down if a write or sleep fails.
            for mouse, code in reversed(held):
                try:
                    self._emit(EV_KEY, code, 0, mouse=mouse)
                    self._emit(EV_SYN, SYN_REPORT, 0, mouse=mouse)
                except OSError:
                    log.exception("could not release input code %s", code)

    def close(self) -> None:
        for attr in ("_mouse_fd", "_fd"):
            fd = getattr(self, attr)
            if fd is None:
                continue
            setattr(self, attr, None)
            try:
                fcntl.ioctl(fd, UI_DEV_DESTROY)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
