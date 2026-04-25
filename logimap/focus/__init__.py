"""Focus-source implementations — KWin D-Bus primary, xprop poll fallback."""

from .kwin_dbus import KWinFocusSource, WindowFocus

__all__ = ["KWinFocusSource", "WindowFocus"]
