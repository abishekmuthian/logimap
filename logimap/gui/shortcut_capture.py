"""Tk widget that captures a keyboard shortcut on press and emits a canonical string."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

_MOD_MASK = {
    0x0001: "shift",
    0x0004: "ctrl",
    0x0008: "alt",    # Mod1
    0x00040000: "logo",  # Mod4 on most Linux X11 keymaps
}

_KEYSYM_MAP = {
    "Return": "return",
    "Escape": "escape",
    "Tab": "tab",
    "BackSpace": "backspace",
    "Delete": "delete",
    "space": "space",
    "Home": "home",
    "End": "end",
    "Prior": "pageup",
    "Next": "pagedown",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
}


def _normalize(event: tk.Event) -> str | None:
    keysym = event.keysym
    if keysym in {
        "Control_L", "Control_R", "Shift_L", "Shift_R",
        "Alt_L", "Alt_R", "Meta_L", "Meta_R",
        "Super_L", "Super_R",
    }:
        return None

    modifiers: list[str] = []
    for mask, name in _MOD_MASK.items():
        if event.state & mask:
            modifiers.append(name)
    # Keep a canonical order
    order = {"ctrl": 0, "shift": 1, "alt": 2, "logo": 3}
    modifiers.sort(key=lambda m: order.get(m, 99))

    if keysym in _KEYSYM_MAP:
        key = _KEYSYM_MAP[keysym]
    elif len(keysym) == 1 and keysym.isalpha():
        key = keysym.lower()
    elif keysym.startswith("F") and keysym[1:].isdigit():
        key = keysym.lower()
    elif len(keysym) == 1:
        key = keysym
    else:
        key = keysym.lower()

    return "+".join(modifiers + [key])


class ShortcutCapture(ttk.Frame):
    """Click to focus, then press any key combo. The combo string appears below.

    The entry is also directly editable so users can type shortcuts the
    compositor intercepts (e.g. Meta+L on KDE Plasma 6) — those never reach
    Tk via Capture because KWin grabs them globally.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        initial: str = "",
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._on_change = on_change
        self._value = tk.StringVar(value=initial)
        self._suppress_trace = False

        self._entry = ttk.Entry(self, textvariable=self._value, width=30)
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._btn = ttk.Button(self, text="Capture", command=self._start_capture)
        self._btn.grid(row=0, column=1)
        self._clear = ttk.Button(self, text="Clear", command=self._do_clear)
        self._clear.grid(row=0, column=2, padx=(4, 0))
        self.columnconfigure(0, weight=1)

        self._capturing = False
        self._value.trace_add("write", self._on_value_write)

    def _on_value_write(self, *_args: object) -> None:
        # Fires for user typing/paste AND programmatic .set(); suppress the
        # latter so loading a binding or showing a placeholder doesn't loop
        # back into the caller's on_change.
        if self._suppress_trace or self._capturing:
            return
        if self._on_change is not None:
            self._on_change(self._value.get())

    def get(self) -> str:
        return self._value.get()

    def set(self, value: str) -> None:
        self._suppress_trace = True
        try:
            self._value.set(value)
        finally:
            self._suppress_trace = False

    def _start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self._btn.configure(text="Press keys…")
        self._suppress_trace = True
        try:
            self._value.set("(press any combo)")
        finally:
            self._suppress_trace = False
        self._entry.focus_set()
        self._entry.bind("<Key>", self._on_key)

    def _on_key(self, event: tk.Event) -> str | None:
        combo = _normalize(event)
        if combo is None:
            return "break"
        self._capturing = False
        self._btn.configure(text="Capture")
        self._entry.unbind("<Key>")
        self._suppress_trace = True
        try:
            self._value.set(combo)
        finally:
            self._suppress_trace = False
        if self._on_change is not None:
            self._on_change(combo)
        return "break"

    def _do_clear(self) -> None:
        self._value.set("")
