"""3x3 keypad grid widget with selection and drag-and-drop rearrangement."""

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
    """Click to select a key; drag between cells to rearrange bindings."""

    PREVIEW_SIZE = 118  # start at the LCD's native size, then fit the window
    MIN_PREVIEW_SIZE = 72
    DRAG_THRESHOLD = 6  # px, so a slightly shaky click still only selects

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select: Callable[[str], None] | None = None,
        on_reorder: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=8)
        self._on_select = on_select
        self._on_reorder = on_reorder
        self._selected: str | None = None
        self._labels: dict[str, ttk.Label] = {}
        self._photo_refs: dict[str, ImageTk.PhotoImage] = {}
        self._images: dict[str, bytes] = {}
        self._profile: Profile | None = None
        self._page = 0
        self._preview_size = self.PREVIEW_SIZE
        self._resize_after: str | None = None
        self._drag_source: str | None = None
        self._drag_origin = (0, 0)
        self._dragging = False
        self._drop_target: str | None = None

        self.bind("<Escape>", self._escape_drag)
        self.bind("<FocusOut>", self._cancel_drag)
        self.bind("<Configure>", self._schedule_resize)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

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
                for widget in (lbl, cell):
                    widget.bind("<Button-1>", lambda e, n=name: self._on_press(e, n))
                    widget.bind("<B1-Motion>", self._on_motion)
                    widget.bind("<ButtonRelease-1>", self._on_release)
                self._labels[name] = lbl

    def _schedule_resize(self, _event: tk.Event) -> None:
        if self._resize_after is not None:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(40, self._resize_preview)

    def _resize_preview(self) -> None:
        self._resize_after = None
        # Account for frame padding and each cell's border/padding/gaps.
        size = max(self.MIN_PREVIEW_SIZE,
                   (min(self.winfo_width(), self.winfo_height()) - 16) // 3 - 18)
        if size == self._preview_size:
            return
        self._cancel_drag()
        self._preview_size = size
        if ImageTk is None:
            self._render_text_only(self._profile, self._page)
        else:
            self._render_images()

    def _escape_drag(self, event: tk.Event) -> str | None:
        if self._drag_source is not None:
            self._cancel_drag(event)
            return "break"  # Cancel the drag before leaving fullscreen.
        return None

    def _on_press(self, event: tk.Event, name: str) -> None:
        self._cancel_drag()
        self.focus_set()
        self._select(name)
        self._drag_source = name
        self._drag_origin = (event.x_root, event.y_root)

    def _key_at(self, event: tk.Event) -> str | None:
        # Motion/release events remain on the pressed widget under Tk's
        # implicit pointer grab, so hit-test using screen coordinates.
        widget = self.winfo_containing(event.x_root, event.y_root)
        for name, label in self._labels.items():
            if widget is label or widget is label.master:
                return name
        return None

    def _on_motion(self, event: tk.Event) -> None:
        if self._drag_source is None or self._on_reorder is None:
            return
        if not self._dragging:
            dx = event.x_root - self._drag_origin[0]
            dy = event.y_root - self._drag_origin[1]
            if dx * dx + dy * dy < self.DRAG_THRESHOLD ** 2:
                return
            self._dragging = True
            for label in self._labels.values():
                label.configure(cursor="fleur")
                label.master.configure(cursor="fleur")
        self._drop_target = self._key_at(event)
        self._refresh_highlights()

    def _on_release(self, event: tk.Event) -> None:
        source = self._drag_source
        target = self._key_at(event) if self._dragging else None
        self._cancel_drag()
        if source is not None and target is not None and source != target:
            if self._on_reorder is not None:
                self._on_reorder(source, target)

    def _cancel_drag(self, _event: tk.Event | None = None) -> None:
        self._drag_source = None
        self._dragging = False
        self._drop_target = None
        for label in self._labels.values():
            label.configure(cursor="hand2")
            label.master.configure(cursor="hand2")
        self._refresh_highlights()

    def _select(self, name: str) -> None:
        self._selected = name
        self._refresh_highlights()
        if self._on_select is not None:
            self._on_select(name)

    def select(self, name: str) -> None:
        self._select(name)

    def selected(self) -> str | None:
        return self._selected

    def render_profile(self, profile: Profile | None, page: int = 0) -> None:
        # Changing pages/profiles or editing a binding invalidates a drag.
        self._cancel_drag()
        self._profile = profile
        self._page = page
        if ImageTk is None:
            self._render_text_only(profile, page)
            return
        if profile is None:
            blank = render.make_blank()
            images = {name: blank for name in KEY_NAMES}
        else:
            titles = {}
            for name in KEY_NAMES:
                binding = profile.get(name, page)
                titles[name] = binding.title if binding and binding.title else ""
            images = render.make_profile_images(
                titles, bg=profile.bg_color, fg=profile.fg_color
            )
        self._images = images
        self._render_images()

    def _render_images(self) -> None:
        # Resize cached grid renders rather than regenerating nine JPEGs on
        # every window resize. The same shared font size still applies.
        for name, jpeg in self._images.items():
            photo = self._jpeg_to_photo(jpeg)
            self._photo_refs[name] = photo
            self._labels[name].configure(image=photo)
        self._refresh_highlights()

    def _render_text_only(self, profile: Profile | None, page: int = 0) -> None:
        font_size = max(12, self._preview_size // 7)
        for name in KEY_NAMES:
            lbl = self._labels[name]
            title = ""
            if profile is not None:
                binding = profile.get(name, page)
                if binding:
                    title = binding.title
            lbl.configure(
                text=title or "(empty)",
                image="",
                width=max(1, int(self._preview_size / (font_size * 0.65))),
                wraplength=self._preview_size,
                font=("", -font_size),
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
        img = img.resize((self._preview_size, self._preview_size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _refresh_highlights(self) -> None:
        for name, lbl in self._labels.items():
            parent = lbl.master
            if name == self._drop_target and name != self._drag_source:
                parent.configure(relief="raised", borderwidth=4)
            elif self._dragging and name == self._drag_source:
                parent.configure(relief="sunken", borderwidth=3)
            elif name == self._selected:
                parent.configure(relief="solid", borderwidth=3)
            else:
                parent.configure(relief="groove", borderwidth=2)
