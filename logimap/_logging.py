"""Shared logging setup: stderr + rotating file at ~/.local/state/logimap/logimap.log."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "logimap"
LOG_PATH = LOG_DIR / "logimap.log"

_FMT = "%(asctime)s %(name)s %(levelname)s %(message)s"


def setup(verbose: bool = False, log_to_file: bool = True) -> Path | None:
    """Configure root logger.

    Returns the log path on disk (or None if file logging is disabled/failed).
    """
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)

    # Clear any pre-existing handlers (tests, re-init, etc.)
    for h in list(root.handlers):
        root.removeHandler(h)

    stderr = logging.StreamHandler()
    stderr.setFormatter(logging.Formatter(_FMT))
    stderr.setLevel(level)
    root.addHandler(stderr)

    if not log_to_file:
        return None

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(LOG_PATH, maxBytes=1_048_576, backupCount=3)
        fh.setFormatter(logging.Formatter(_FMT))
        fh.setLevel(level)
        root.addHandler(fh)
        return LOG_PATH
    except OSError:
        root.warning("could not open log file %s — stderr only", LOG_PATH)
        return None
