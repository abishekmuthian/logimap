"""logimap daemon: wire focus source + keypad + shortcut injector + config."""

from __future__ import annotations

import logging
import signal
import threading

from logilinux import MXKeypadButton

from . import render
from .config import Config
from .device import GRID_BUTTONS, KeypadHandle, KeypadUnavailable
from .focus.kwin_dbus import KWinFocusSource
from .inject import get_injector
from .profiles import Profile, WindowFocus, resolve

log = logging.getLogger(__name__)

PAINT_RETRY_SECONDS = 2.0


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
        self._paint_requested = threading.Event()
        self._lock = threading.Lock()
        self._current: Profile | None = None
        self._pages: dict[str, int] = {}
        self._page = 0
        self._painted: tuple[int, int] | None = None
        self._pending_profile: Profile | None = None
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
        retry = threading.Thread(target=self._retry_paint, daemon=True, name="paint-retry")
        retry.start()

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
            self._pages = {
                name: min(page, self._config.profiles[name].page_count - 1)
                for name, page in self._pages.items()
                if name in self._config.profiles
            }
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
        page = self._pages.get(profile.name, 0)
        if (
            self._current is profile
            and self._painted == (id(profile), page)
            and self._pending_profile is None
        ):
            return
        self._current = profile
        self._page = page
        self._paint_or_defer(profile)

    def _paint_or_defer(self, profile: Profile) -> None:
        if self._paint_profile(profile):
            self._painted = (id(profile), self._page)
            self._pending_profile = None
            return
        self._painted = None
        self._pending_profile = profile
        log.info("will retry painting profile %s when keypad is available", profile.name)

    def _paint_profile(self, profile: Profile) -> bool:
        log.info("painting profile: %s page %d/%d", profile.name, self._page + 1, profile.page_count)
        titles: dict[MXKeypadButton, str] = {}
        for btn in GRID_BUTTONS:
            binding = profile.get(btn.name, self._page)
            titles[btn] = binding.title if binding and binding.title else ""
        images = render.make_profile_images(
            titles, bg=profile.bg_color, fg=profile.fg_color
        )
        return self._handle.paint_grid(images)

    def _retry_paint(self) -> None:
        while not self._stop.is_set():
            self._paint_requested.wait(PAINT_RETRY_SECONDS)
            self._paint_requested.clear()
            if self._stop.is_set():
                return
            with self._lock:
                if (
                    self._pending_profile is None
                    and self._current is not None
                    and not self._handle.is_monitoring()
                ):
                    self._painted = None
                    self._pending_profile = self._current
                if self._pending_profile is not None:
                    self._paint_or_defer(self._pending_profile)

    def _on_button(self, btn: MXKeypadButton) -> None:
        with self._lock:
            profile = self._current
            if profile is not None:
                if btn in (MXKeypadButton.P1_LEFT, MXKeypadButton.P2_RIGHT):
                    if profile.page_count > 1:
                        step = -1 if btn == MXKeypadButton.P1_LEFT else 1
                        self._page = (self._page + step) % profile.page_count
                        self._pages[profile.name] = self._page
                        # The SDK calls us on its monitoring thread. Repainting
                        # can reconnect and stop that thread, so let the worker
                        # perform all navigation-triggered device I/O.
                        self._painted = None
                        self._pending_profile = profile
                        self._paint_requested.set()
                    return
                binding = profile.get(btn.name, self._page)
        if profile is None:
            log.info("press %s ignored — no active profile yet", btn.name)
            return
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
