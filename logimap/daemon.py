"""logimap daemon: wire focus source + keypad + shortcut injector + config."""

from __future__ import annotations

import logging
import signal
import threading
from typing import Callable

from logilinux import MXKeypadButton

from . import render
from .config import Config
from .device import GRID_BUTTONS, KeypadHandle, KeypadUnavailable
from .focus.kwin_dbus import KWinFocusSource
from .inject import get_injector
from .profiles import Profile, WindowFocus, resolve

log = logging.getLogger(__name__)


class Daemon:
    def __init__(self) -> None:
        self._config = Config.load()
        self._handle = KeypadHandle()
        try:
            self._injector = get_injector()
        except RuntimeError as e:
            log.error("%s", e)
            self._injector = None
        self._focus = KWinFocusSource()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._current: Profile | None = None
        self._last_focus: WindowFocus | None = None

    def run(self) -> int:
        signal.signal(signal.SIGTERM, lambda *_: self._stop.set())
        signal.signal(signal.SIGINT, lambda *_: self._stop.set())
        signal.signal(signal.SIGHUP, lambda *_: self._reload())

        try:
            self._handle.open()
        except KeypadUnavailable as e:
            log.error("keypad not ready: %s", e)

        self._handle.on_press(self._on_button)
        self._focus.subscribe(self._on_focus)

        # background config file watcher
        watcher = threading.Thread(target=self._watch_config, daemon=True, name="config-watch")
        watcher.start()

        log.info("daemon running — Ctrl+C to stop")
        try:
            while not self._stop.wait(1.0):
                pass
        finally:
            self._focus.stop()
            self._handle.close()
        return 0

    def _reload(self) -> None:
        with self._lock:
            log.info("reloading config")
            self._config = Config.load(self._config.path)
            if self._last_focus is not None:
                self._apply_focus(self._last_focus)

    def _watch_config(self) -> None:
        last = self._config.mtime()
        while not self._stop.wait(1.0):
            cur = self._config.mtime()
            if cur != last:
                last = cur
                self._reload()

    def _on_focus(self, focus: WindowFocus) -> None:
        log.info(
            "focus -> wm_class=%r resource_name=%r pid=%s caption=%r",
            focus.wm_class, focus.resource_name, focus.pid, focus.caption,
        )
        with self._lock:
            self._last_focus = focus
            self._apply_focus(focus)

    def _apply_focus(self, focus: WindowFocus) -> None:
        profile = resolve(self._config.profiles, focus, self._config.default_profile)
        if self._current is not None and profile.name == self._current.name:
            return
        self._current = profile
        self._paint_profile(profile)

    def _paint_profile(self, profile: Profile) -> None:
        log.info("painting profile: %s", profile.name)
        titles: dict[MXKeypadButton, str] = {}
        for btn in GRID_BUTTONS:
            binding = profile.keys.get(btn.name)
            titles[btn] = binding.title if binding and binding.title else ""
        images = render.make_profile_images(
            titles, bg=profile.bg_color, fg=profile.fg_color
        )
        self._handle.paint_grid(images)

    def _on_button(self, btn: MXKeypadButton) -> None:
        with self._lock:
            profile = self._current
        if profile is None:
            log.info("press %s ignored — no active profile yet", btn.name)
            return
        binding = profile.keys.get(btn.name)
        if binding is None or not binding.shortcut:
            log.info("press %s has no binding in profile %r", btn.name, profile.name)
            return
        if self._injector is None:
            log.warning("no injector available — cannot fire %s", binding.shortcut)
            return
        log.info("firing %s -> %s", btn.name, binding.shortcut)
        try:
            self._injector.press(binding.shortcut)
        except Exception:
            log.exception("injector.press failed for %s", binding.shortcut)
