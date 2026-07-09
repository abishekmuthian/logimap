"""Thin wrapper around logilinux.MXKeypadDevice with auto-reconnect."""

from __future__ import annotations

import logging
import time
from threading import Event as ThreadEvent, RLock
from typing import Callable

from logilinux import (
    ButtonEvent,
    DeviceType,
    Library,
    MXKeypadButton,
    MXKeypadDevice,
)

from . import render

log = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 2.0

GRID_BUTTONS: tuple[MXKeypadButton, ...] = (
    MXKeypadButton.GRID_0,
    MXKeypadButton.GRID_1,
    MXKeypadButton.GRID_2,
    MXKeypadButton.GRID_3,
    MXKeypadButton.GRID_4,
    MXKeypadButton.GRID_5,
    MXKeypadButton.GRID_6,
    MXKeypadButton.GRID_7,
    MXKeypadButton.GRID_8,
)


class KeypadUnavailable(RuntimeError):
    pass


class KeypadHandle:
    """Wrap an MXKeypadDevice and expose paint + press-callback helpers.

    Reconnects automatically if `set_key_image` errors (likely an unplug).
    """

    def __init__(self) -> None:
        self._lib = Library()
        self._device: MXKeypadDevice | None = None
        self._lock = RLock()
        self._stop = ThreadEvent()
        self._press_cb: Callable[[MXKeypadButton], None] | None = None

    def open(self) -> None:
        with self._lock:
            self._open_locked()

    def _open_locked(self) -> None:
        dev = self._lib.find_device(DeviceType.MX_KEYPAD)
        if dev is None:
            raise KeypadUnavailable("MX Keypad not found — is it plugged in?")
        if not isinstance(dev, MXKeypadDevice):
            raise KeypadUnavailable(f"Expected MXKeypadDevice, got {type(dev).__name__}")
        if not dev.initialize():
            raise KeypadUnavailable("MXKeypadDevice.initialize() returned False")
        if not dev.has_lcd():
            raise KeypadUnavailable("Device reports no LCD capability")
        dev.set_event_callback(self._on_native_event)
        dev.start_monitoring()
        self._device = dev
        log.info("keypad opened: %s", dev.info)

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._drop_device_locked()

    def on_press(self, cb: Callable[[MXKeypadButton], None]) -> None:
        self._press_cb = cb

    def is_monitoring(self) -> bool:
        with self._lock:
            return self._device is not None and bool(self._device.is_monitoring)

    def paint(self, button: MXKeypadButton, jpeg: bytes) -> bool:
        idx = int(button.value)
        if idx < 0 or idx > 8:
            # set_key_image targets grid buttons only (0-8). P1/P2 are input-only.
            return False
        return self._with_retry(lambda dev: dev.set_key_image(idx, jpeg))

    def paint_grid(self, images: dict[MXKeypadButton, bytes]) -> bool:
        """Paint every grid button. Missing keys are cleared to blank.

        The whole 9-key sequence runs under self._lock so concurrent callers
        (focus-change thread, config-watch thread) cannot interleave native
        set_key_image calls — the underlying C++ PacketBufferPool is a 16-slot
        counter-mod ring with no release, and one full grid repaint already
        wraps it. See logilinux/logilinux#5.
        """
        blank = render.make_blank()
        with self._lock:
            for btn in GRID_BUTTONS:
                if not self.paint(btn, images.get(btn, blank)):
                    return False
        return True

    def _with_retry(self, op: Callable[[MXKeypadDevice], bool]) -> bool:
        with self._lock:
            if self._device is None:
                try:
                    self._open_locked()
                except KeypadUnavailable as e:
                    log.warning("keypad unavailable: %s", e)
                    return False
            try:
                if bool(op(self._device)):
                    return True
                log.warning("device op failed — attempting reconnect")
            except Exception:
                log.exception("device op failed — attempting reconnect")
            self._drop_device_locked()
            time.sleep(RECONNECT_DELAY_SECONDS)
            try:
                self._open_locked()
                return bool(op(self._device))
            except Exception:
                log.exception("reconnect failed")
                self._drop_device_locked()
                return False

    def _drop_device_locked(self) -> None:
        if self._device is None:
            return
        try:
            self._device.stop_monitoring()
        except Exception:
            log.exception("stop_monitoring failed")
        self._device = None

    def _on_native_event(self, event) -> None:
        if not isinstance(event, ButtonEvent) or not event.pressed:
            return
        try:
            button = event.get_mx_keypad_button()
        except Exception:
            log.exception("bad button event: %r", event)
            return
        if self._press_cb is not None:
            try:
                self._press_cb(button)
            except Exception:
                log.exception("press callback raised")


def paint_test() -> int:
    """`logimap paint-test`: paint GRID_0..GRID_8 with numeric titles and exit after 30 s."""
    handle = KeypadHandle()
    try:
        handle.open()
    except KeypadUnavailable as e:
        log.error("%s", e)
        return 1

    titles = {
        MXKeypadButton.GRID_0: "New Tab",
        MXKeypadButton.GRID_1: "Close",
        MXKeypadButton.GRID_2: "Reopen",
        MXKeypadButton.GRID_3: "Find",
        MXKeypadButton.GRID_4: "Save",
        MXKeypadButton.GRID_5: "Copy",
        MXKeypadButton.GRID_6: "Paste",
        MXKeypadButton.GRID_7: "Undo",
        MXKeypadButton.GRID_8: "Redo",
    }
    images = render.make_profile_images(titles)
    handle.paint_grid(images)

    def _on_press(btn: MXKeypadButton) -> None:
        log.info("pressed: %s", btn.name)

    handle.on_press(_on_press)

    try:
        log.info("painted 9 keys — press Ctrl+C to exit")
        while not handle._stop.wait(1.0):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        handle.close()
    return 0
