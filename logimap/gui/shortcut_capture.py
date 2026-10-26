"""Capture keyboard shortcuts or mouse clicks as canonical shortcut strings."""

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


_MOUSE_BUTTON_MAP = {
    1: "mouse_left", 2: "mouse_middle", 3: "mouse_right",
    8: "mouse_back", 9: "mouse_forward",
}


def _modifiers(state: int) -> list[str]:
    modifiers = [name for mask, name in _MOD_MASK.items() if state & mask]
    order = {"ctrl": 0, "shift": 1, "alt": 2, "logo": 3}
    return sorted(modifiers, key=lambda m: order[m])


def _normalize_mouse(event: tk.Event) -> str | None:
    key = _MOUSE_BUTTON_MAP.get(event.num)
    if key is None:
        return None  # Tk buttons 4–7 are wheel events, not side buttons.
    return "+".join(_modifiers(event.state) + [key])


def _normalize(event: tk.Event) -> str | None:
    keysym = event.keysym
    if keysym in {
        "Control_L", "Control_R", "Shift_L", "Shift_R",
        "Alt_L", "Alt_R", "Meta_L", "Meta_R",
        "Super_L", "Super_R",
    }:
        return None

    modifiers = _modifiers(event.state)

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
    """Capture a key combo or click in the entry. The string appears below.

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
        self._hint = ttk.Label(
            self, text="Type timing in ms: mouse_right@500,wait:300,mouse_left. Capture a key or click.",
            foreground="grey50",
            wraplength=360,
        )
        self._hint.grid(row=1, column=0, columnspan=3, sticky="w")
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
        self._cancel_capture()
        self._suppress_trace = True
        try:
            self._value.set(value)
        finally:
            self._suppress_trace = False

    def _start_capture(self) -> None:
        if self._capturing:
            return
        self._capture_value = self._value.get()
        self._capturing = True
        self._btn.configure(text="Key or click…")
        self._suppress_trace = True
        try:
            self._value.set("(press keys or click here)")
        finally:
            self._suppress_trace = False
        self._entry.focus_set()
        self._entry.bind("<Key>", self._on_key)
        self._entry.bind("<ButtonPress>", self._on_mouse)
        self._entry.bind("<FocusOut>", lambda _e: self._cancel_capture())

    def _on_key(self, event: tk.Event) -> str | None:
        combo = _normalize(event)
        if combo is None:
            return "break"
        return self._finish_capture(combo)

    def _on_mouse(self, event: tk.Event) -> str:
        combo = _normalize_mouse(event)
        if combo is not None:
            return self._finish_capture(combo)
        return "break"

    def _cancel_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self._btn.configure(text="Capture")
        for sequence in ("<Key>", "<ButtonPress>", "<FocusOut>"):
            self._entry.unbind(sequence)
        self.set(self._capture_value)

    def _finish_capture(self, combo: str) -> str:
        self._cancel_capture()
        self._suppress_trace = True
        try:
            self._value.set(combo)
        finally:
            self._suppress_trace = False
        if self._on_change is not None:
            self._on_change(combo)
        return "break"

    def _do_clear(self) -> None:
        self._cancel_capture()
        self._value.set("")
