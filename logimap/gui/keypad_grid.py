"""3x3 keypad grid widget — a clickable representation of the 9 LCD buttons."""

from __future__ import annotations

import tkinter as tk
from io import BytesIO
from tkinter import ttk
from typing import Callable

from PIL import Image

try:
    from PIL import ImageTk  # requires python3-pillow-tk on Fedora
except ImportError as _e:  # pragma: no cover
    ImageTk = None  # type: ignore[assignment]
    _IMAGETK_ERROR = _e
else:
    _IMAGETK_ERROR = None

from .. import render
from ..profiles import KEY_NAMES, Profile


class KeypadGrid(ttk.Frame):
    """Shows a 3x3 grid of the current profile's keys; clicking selects one."""

    PREVIEW_SIZE = 72  # px on-screen

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=8)
        self._on_select = on_select
        self._selected: str | None = None
        self._labels: dict[str, ttk.Label] = {}
        self._photo_refs: dict[str, ImageTk.PhotoImage] = {}

        grid_frame = ttk.Frame(self)
        grid_frame.grid(row=0, column=0)
        for row in range(3):
            for col in range(3):
                idx = row * 3 + col
                name = KEY_NAMES[idx]
                cell = ttk.Frame(grid_frame, borderwidth=2, relief="groove", padding=2)
                cell.grid(row=row, column=col, padx=3, pady=3)
                lbl = ttk.Label(cell, cursor="hand2", width=0)
                lbl.grid()
                lbl.bind("<Button-1>", lambda _e, n=name: self._select(n))
                cell.bind("<Button-1>", lambda _e, n=name: self._select(n))
                self._labels[name] = lbl

    def _select(self, name: str) -> None:
        self._selected = name
        self._refresh_highlights()
        if self._on_select is not None:
            self._on_select(name)

    def select(self, name: str) -> None:
        self._select(name)

    def selected(self) -> str | None:
        return self._selected

    def render_profile(self, profile: Profile | None) -> None:
        if ImageTk is None:
            self._render_text_only(profile)
            return
        for name in KEY_NAMES:
            lbl = self._labels[name]
            if profile is None:
                jpeg = render.make_blank()
            else:
                binding = profile.keys.get(name)
                title = binding.title if binding else ""
                if title:
                    jpeg = render.make_key_image(
                        title,
                        bg=profile.bg_color,
                        fg=profile.fg_color,
                    )
                else:
                    jpeg = render.make_blank(profile.bg_color)
            photo = self._jpeg_to_photo(jpeg)
            self._photo_refs[name] = photo
            lbl.configure(image=photo)
        self._refresh_highlights()

    def _render_text_only(self, profile: Profile | None) -> None:
        for name in KEY_NAMES:
            lbl = self._labels[name]
            title = ""
            if profile is not None:
                binding = profile.keys.get(name)
                if binding:
                    title = binding.title
            lbl.configure(
                text=title or "(empty)",
                image="",
                width=self.PREVIEW_SIZE // 6,
                wraplength=self.PREVIEW_SIZE,
                foreground="white" if title else "gray",
                background="#202020",
                padding=4,
            )
            # ttk.Label cannot guarantee sizing without an image — pad with a minimum height
        self._refresh_highlights()

    def _jpeg_to_photo(self, jpeg: bytes):
        if ImageTk is None:
            raise RuntimeError(
                "PIL.ImageTk is not available — install python3-pillow-tk "
                "(`sudo dnf install python3-pillow-tk`) to use the GUI."
            )
        img = Image.open(BytesIO(jpeg))
        img = img.resize((self.PREVIEW_SIZE, self.PREVIEW_SIZE))
        return ImageTk.PhotoImage(img)

    def _refresh_highlights(self) -> None:
        for name, lbl in self._labels.items():
            parent = lbl.master
            if name == self._selected:
                parent.configure(relief="solid", borderwidth=3)
            else:
                parent.configure(relief="groove", borderwidth=2)
