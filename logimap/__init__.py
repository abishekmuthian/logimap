"""logimap — per-application profile manager for the Logitech MX Keypad."""

from importlib.metadata import PackageNotFoundError, version as _v

try:
    __version__ = _v("logimap")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
