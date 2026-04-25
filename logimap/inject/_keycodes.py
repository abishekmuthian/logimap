"""Linux input-event keycode tables shared by uinput / ydotool injectors.

Codes match <linux/input-event-codes.h>. We use the 'left' variant for every
modifier; that's what /dev/uinput synthesizes when a real keyboard sends a
modified shortcut.
"""

from __future__ import annotations

MOD_CODE: dict[str, int] = {
    "ctrl": 29,   # KEY_LEFTCTRL
    "shift": 42,  # KEY_LEFTSHIFT
    "alt": 56,    # KEY_LEFTALT
    "logo": 125,  # KEY_LEFTMETA
}

KEY_CODE: dict[str, int] = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "0": 11, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8,
    "8": 9, "9": 10,
    "return": 28, "enter": 28,
    "esc": 1, "escape": 1,
    "tab": 15, "space": 57, "backspace": 14,
    "delete": 111, "del": 111,
    "home": 102, "end": 107,
    "pageup": 104, "pagedown": 109,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "insert": 110, "menu": 127,
    "minus": 12, "equal": 13,
    "comma": 51, "period": 52, "slash": 53,
    "semicolon": 39, "apostrophe": 40, "grave": 41,
    "leftbrace": 26, "rightbrace": 27, "backslash": 43,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
}
