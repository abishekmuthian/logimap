"""KWin-based focus source: load a KWin JS script, receive D-Bus pings."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dbus_next import BusType, Message, RequestNameReply  # type: ignore
from dbus_next.aio import MessageBus  # type: ignore
from dbus_next.service import ServiceInterface, method  # type: ignore

from ..profiles import WindowFocus

log = logging.getLogger(__name__)

SERVICE_NAME = "org.logimap.Focus1"
OBJECT_PATH = "/org/logimap/Focus1"
INTERFACE = "org.logimap.Focus1"

KWIN_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "kwin_script" / "logimap-focus.js"
KWIN_SCRIPT_NAME = "logimap-focus"


class _FocusInterface(ServiceInterface):
    def __init__(self, callback: Callable[[WindowFocus], None]):
        super().__init__(INTERFACE)
        self._cb = callback

    @method()
    def Notify(self, resourceClass: "s", resourceName: "s", caption: "s", pid: "i"):  # type: ignore[valid-type]
        focus = WindowFocus(
            wm_class=resourceClass,
            resource_name=resourceName,
            caption=caption,
            pid=pid if pid > 0 else None,
        )
        try:
            self._cb(focus)
        except Exception:
            log.exception("focus callback raised")


class KWinFocusSource:
    """Owns the org.logimap.Focus1 service; re-emits WindowFocus to a callback.

    Runs an asyncio event loop on a background thread so callers can remain
    synchronous.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._bus: MessageBus | None = None
        self._callback: Callable[[WindowFocus], None] | None = None
        self._ready = threading.Event()
        self._stop_event: asyncio.Event | None = None

    def subscribe(self, callback: Callable[[WindowFocus], None]) -> None:
        if self._thread is not None:
            raise RuntimeError("already subscribed")
        self._callback = callback
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kwin-focus")
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("KWinFocusSource failed to start within 5 s")

    def stop(self) -> None:
        loop = self._loop
        stop = self._stop_event
        if loop is None or stop is None:
            return
        loop.call_soon_threadsafe(stop.set)
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        finally:
            loop.close()

    async def _main(self) -> None:
        assert self._callback is not None
        self._stop_event = asyncio.Event()
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self._bus = bus

        iface = _FocusInterface(self._callback)
        bus.export(OBJECT_PATH, iface)
        reply = await bus.request_name(SERVICE_NAME)
        if reply != RequestNameReply.PRIMARY_OWNER:
            log.warning("could not become primary owner of %s (reply=%s)", SERVICE_NAME, reply)
        else:
            log.info("owning %s — waiting for KWin focus events", SERVICE_NAME)

        try:
            await _ensure_script_loaded(bus)
        except Exception:
            log.exception("failed to load KWin focus script — is Plasma running?")

        self._ready.set()
        await self._stop_event.wait()
        bus.disconnect()


async def _ensure_script_loaded(bus: MessageBus) -> None:
    """Load logimap-focus.js via org.kde.kwin.Scripting if not already loaded.

    The API on Plasma 6:
      - org.kde.KWin / Scripting / loadScript(path, pluginName) -> int scriptId
      - /<scriptId> .run()
      - isScriptLoaded(pluginName) -> bool
    """
    if not KWIN_SCRIPT_PATH.exists():
        raise FileNotFoundError(f"KWin script missing: {KWIN_SCRIPT_PATH}")

    already = await _call(
        bus,
        destination="org.kde.KWin",
        path="/Scripting",
        interface="org.kde.kwin.Scripting",
        member="isScriptLoaded",
        signature="s",
        body=[KWIN_SCRIPT_NAME],
    )
    if already and already.body and already.body[0]:
        log.info("KWin script '%s' already loaded", KWIN_SCRIPT_NAME)
        return

    reply = await _call(
        bus,
        destination="org.kde.KWin",
        path="/Scripting",
        interface="org.kde.kwin.Scripting",
        member="loadScript",
        signature="ss",
        body=[str(KWIN_SCRIPT_PATH), KWIN_SCRIPT_NAME],
    )
    if not reply or not reply.body:
        raise RuntimeError("loadScript returned no body")
    script_id = int(reply.body[0])
    log.info("loaded KWin script '%s' -> id=%d", KWIN_SCRIPT_NAME, script_id)

    await _call(
        bus,
        destination="org.kde.KWin",
        path=f"/Scripting/Script{script_id}",
        interface="org.kde.kwin.Script",
        member="run",
        signature="",
        body=[],
    )
    log.info("KWin script '%s' running", KWIN_SCRIPT_NAME)


async def _call(
    bus: MessageBus,
    *,
    destination: str,
    path: str,
    interface: str,
    member: str,
    signature: str,
    body: list,
):
    msg = Message(
        destination=destination,
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=body,
    )
    return await bus.call(msg)


def install_kwin_script() -> int:
    """`logimap install-kwin` entry point — load script and exit."""
    async def _main() -> int:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        try:
            await _ensure_script_loaded(bus)
            return 0
        finally:
            bus.disconnect()

    try:
        return asyncio.run(_main())
    except Exception as e:
        log.error("install-kwin failed: %s", e)
        return 1
