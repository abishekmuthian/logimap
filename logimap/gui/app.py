"""Tk GUI: edit profiles, preview keys, push to device."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..config import Config
from ..profiles import KEY_NAMES, KeyBinding, Match, Profile
from .. import render
from .keypad_grid import KeypadGrid
from .shortcut_capture import ShortcutCapture

log = logging.getLogger(__name__)


class LogimapApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = Config.load()
        self.current_profile_name: str | None = self._initial_profile()
        self._handle: KeypadHandle | None = None

        root.title("logimap — keypad profile editor")
        root.geometry("1100x560")
        root.minsize(1000, 520)

        self._build_layout()
        self._refresh_profiles()
        if self.current_profile_name:
            self._select_profile(self.current_profile_name)

    def _initial_profile(self) -> str | None:
        names = list(self.config.profiles.keys())
        for n in names:
            if n != "default":
                return n
        return names[0] if names else None

    def _build_layout(self) -> None:
        root = self.root

        toolbar = ttk.Frame(root, padding=6)
        toolbar.pack(side="top", fill="x")
        ttk.Label(toolbar, text="Profile:").pack(side="left")
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(toolbar, textvariable=self.profile_var, state="readonly", width=30)
        self.profile_combo.pack(side="left", padx=(4, 8))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._select_profile(self.profile_var.get()))

        ttk.Button(toolbar, text="Add", command=self._add_profile).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Duplicate", command=self._duplicate_profile).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Delete", command=self._delete_profile).pack(side="left", padx=2)

        ttk.Button(toolbar, text="Save", command=self._save).pack(side="right", padx=2)
        ttk.Button(toolbar, text="Push to device", command=self._push_to_device).pack(side="right", padx=2)

        self.status = ttk.Label(root, anchor="w", padding=6, foreground="gray")
        self.status.pack(side="bottom", fill="x")

        main = ttk.Frame(root, padding=6)
        main.pack(side="top", fill="both", expand=True)

        # Left: keypad grid preview
        left = ttk.Frame(main)
        left.pack(side="left", fill="y", padx=(0, 12))
        ttk.Label(left, text="Preview (click a key to edit)", font=("", 10, "bold")).pack(anchor="w")
        self.grid = KeypadGrid(left, on_select=self._on_key_select)
        self.grid.pack()

        # Right: edit pane
        right = ttk.Frame(main)
        right.pack(side="left", fill="both", expand=True)

        match_box = ttk.LabelFrame(right, text="Match", padding=6)
        match_box.pack(side="top", fill="x", pady=(0, 6))
        ttk.Label(match_box, text="Window class (wm_class):").grid(row=0, column=0, sticky="w")
        self.wm_class_var = tk.StringVar()
        ttk.Entry(match_box, textvariable=self.wm_class_var, width=30).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(match_box, text="Title regex (optional):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.title_regex_var = tk.StringVar()
        ttk.Entry(match_box, textvariable=self.title_regex_var, width=30).grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        match_box.columnconfigure(1, weight=1)

        self.key_frame = ttk.LabelFrame(right, text="Selected key", padding=6)
        self.key_frame.pack(side="top", fill="x", pady=6)

        ttk.Label(self.key_frame, text="Key:").grid(row=0, column=0, sticky="w")
        self.selected_key_label = ttk.Label(self.key_frame, text="(none selected)", foreground="gray")
        self.selected_key_label.grid(row=0, column=1, sticky="w")

        ttk.Label(self.key_frame, text="Title:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(self.key_frame, textvariable=self.title_var, width=30)
        self.title_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.title_var.trace_add("write", lambda *_: self._title_changed())

        ttk.Label(self.key_frame, text="Shortcut:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.shortcut_widget = ShortcutCapture(self.key_frame, on_change=self._shortcut_changed)
        self.shortcut_widget.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        self.key_frame.columnconfigure(1, weight=1)

        ttk.Button(self.key_frame, text="Clear key", command=self._clear_key).grid(row=3, column=1, sticky="e", pady=(6, 0))

        self._set_key_enabled(False)

        # Bind match entries to save-on-blur
        self.wm_class_var.trace_add("write", lambda *_: self._match_changed())
        self.title_regex_var.trace_add("write", lambda *_: self._match_changed())

    # ---- profile list ------------------------------------------------------

    def _refresh_profiles(self) -> None:
        names = list(self.config.profiles.keys())
        self.profile_combo["values"] = names
        if self.current_profile_name not in names:
            self.current_profile_name = names[0] if names else None
        if self.current_profile_name:
            self.profile_var.set(self.current_profile_name)

    def _current(self) -> Profile | None:
        if self.current_profile_name is None:
            return None
        return self.config.profiles.get(self.current_profile_name)

    def _select_profile(self, name: str) -> None:
        if name not in self.config.profiles:
            return
        self.current_profile_name = name
        self.profile_var.set(name)
        profile = self._current()
        assert profile is not None
        self.wm_class_var.set(profile.match.wm_class)
        self.title_regex_var.set(profile.match.title_regex or "")
        self.grid.render_profile(profile)
        # Pre-select GRID_0 for convenience
        sel = self.grid.selected() or "GRID_0"
        self.grid.select(sel)

    def _add_profile(self) -> None:
        name = simpledialog.askstring("New profile", "Profile name (e.g. 'firefox'):", parent=self.root)
        if not name:
            return
        name = name.strip()
        if name in self.config.profiles:
            messagebox.showerror("Exists", f"Profile {name!r} already exists.")
            return
        self.config.profiles[name] = Profile(name=name, match=Match(wm_class=name))
        self.current_profile_name = name
        self._refresh_profiles()
        self._select_profile(name)
        self._set_status(f"added {name!r}")

    def _duplicate_profile(self) -> None:
        src = self._current()
        if src is None:
            return
        name = simpledialog.askstring("Duplicate profile", "New name:", parent=self.root, initialvalue=f"{src.name}-copy")
        if not name:
            return
        name = name.strip()
        if name in self.config.profiles:
            messagebox.showerror("Exists", f"Profile {name!r} already exists.")
            return
        copy = Profile(
            name=name,
            match=Match(wm_class=src.match.wm_class, title_regex=src.match.title_regex),
            bg_color=src.bg_color,
            fg_color=src.fg_color,
            keys={k: KeyBinding(v.title, v.shortcut) for k, v in src.keys.items()},
        )
        self.config.profiles[name] = copy
        self.current_profile_name = name
        self._refresh_profiles()
        self._select_profile(name)
        self._set_status(f"duplicated {src.name!r} -> {name!r}")

    def _delete_profile(self) -> None:
        profile = self._current()
        if profile is None:
            return
        if profile.name == "default":
            messagebox.showerror("Cannot delete", "The 'default' profile is required.")
            return
        if not messagebox.askyesno("Delete", f"Delete profile {profile.name!r}?"):
            return
        del self.config.profiles[profile.name]
        self.current_profile_name = None
        self._refresh_profiles()
        if self.current_profile_name:
            self._select_profile(self.current_profile_name)
        self._set_status(f"deleted {profile.name!r}")

    # ---- key editor --------------------------------------------------------

    def _set_key_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.title_entry.configure(state=state)
        for child in self.shortcut_widget.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def _on_key_select(self, key_name: str) -> None:
        profile = self._current()
        if profile is None:
            return
        binding = profile.keys.get(key_name) or KeyBinding()
        self.selected_key_label.configure(text=key_name, foreground="black")
        # temporarily detach traces by using 'set' but avoid loop
        self._suspend_trace = True
        try:
            self.title_var.set(binding.title)
            self.shortcut_widget.set(binding.shortcut)
        finally:
            self._suspend_trace = False
        self._set_key_enabled(True)

    def _title_changed(self) -> None:
        if getattr(self, "_suspend_trace", False):
            return
        key = self.grid.selected()
        profile = self._current()
        if key is None or profile is None:
            return
        binding = profile.keys.get(key) or KeyBinding()
        binding.title = self.title_var.get()
        profile.keys[key] = binding
        self.grid.render_profile(profile)

    def _shortcut_changed(self, value: str) -> None:
        if getattr(self, "_suspend_trace", False):
            return
        key = self.grid.selected()
        profile = self._current()
        if key is None or profile is None:
            return
        binding = profile.keys.get(key) or KeyBinding()
        binding.shortcut = value
        profile.keys[key] = binding

    def _clear_key(self) -> None:
        key = self.grid.selected()
        profile = self._current()
        if key is None or profile is None:
            return
        profile.keys.pop(key, None)
        self.title_var.set("")
        self.shortcut_widget.set("")
        self.grid.render_profile(profile)

    def _match_changed(self) -> None:
        profile = self._current()
        if profile is None:
            return
        profile.match.wm_class = self.wm_class_var.get() or "*"
        regex = self.title_regex_var.get().strip()
        profile.match.title_regex = regex or None

    # ---- save / push -------------------------------------------------------

    def _save(self) -> None:
        try:
            self.config.save()
            self._set_status(f"saved {self.config.path}")
        except Exception as e:
            log.exception("save failed")
            messagebox.showerror("Save failed", str(e))

    def _push_to_device(self) -> None:
        profile = self._current()
        if profile is None:
            messagebox.showinfo("No profile", "Select a profile first.")
            return
        try:
            from ..device import GRID_BUTTONS, KeypadHandle, KeypadUnavailable
        except ImportError as e:
            messagebox.showerror(
                "SDK not available",
                f"Could not import logilinux SDK: {e}\n\n"
                "Launch via scripts/run.sh gui so PYTHONPATH and LD_LIBRARY_PATH are set.",
            )
            return
        if self._handle is None:
            self._handle = KeypadHandle()
            try:
                self._handle.open()
            except KeypadUnavailable as e:
                self._handle = None
                messagebox.showerror("Device not ready", str(e))
                return
        images = {}
        blank = render.make_blank(profile.bg_color)
        for btn in GRID_BUTTONS:
            binding = profile.keys.get(btn.name)
            if binding and binding.title:
                images[btn] = render.make_key_image(binding.title, bg=profile.bg_color, fg=profile.fg_color)
            else:
                images[btn] = blank
        self._handle.paint_grid(images)
        self._set_status(f"pushed {profile.name!r} to device")

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()


def run_gui() -> int:
    root = tk.Tk()
    app = LogimapApp(root)
    try:
        root.mainloop()
    finally:
        app.close()
    return 0
