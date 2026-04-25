"""Load/save profiles.json at ~/.config/logimap/profiles.json."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .profiles import Profile

log = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "logimap"
CONFIG_PATH = CONFIG_DIR / "profiles.json"
SCHEMA_VERSION = 1


@dataclass
class Config:
    profiles: dict[str, Profile] = field(default_factory=dict)
    default_profile: str = "default"
    path: Path = CONFIG_PATH

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        if not path.exists():
            log.info("no config at %s — creating empty", path)
            cfg = cls(path=path)
            cfg.profiles["default"] = Profile(name="default")
            cfg.save()
            return cfg
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError:
            log.exception("config %s is not valid JSON — using empty config", path)
            return cls(path=path, profiles={"default": Profile(name="default")})

        profiles = {
            name: Profile.from_json(name, pdata)
            for name, pdata in (raw.get("profiles") or {}).items()
        }
        if "default" not in profiles:
            profiles["default"] = Profile(name="default")
        return cls(
            profiles=profiles,
            default_profile=str(raw.get("default_profile", "default")),
            path=path,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "default_profile": self.default_profile,
            "profiles": {name: p.to_json() for name, p in self.profiles.items()},
        }
        data = json.dumps(payload, indent=2, sort_keys=True)
        # atomic write
        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=self.path.parent, prefix=".profiles.", suffix=".tmp"
        ) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)
        log.info("saved config to %s", self.path)

    def mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except FileNotFoundError:
            return 0.0


def watch(path: Path, on_change: Callable[[], None], stop) -> None:
    """Block on a 1 Hz mtime poll, calling on_change() when the file changes.

    `stop` is any object with a `.wait(seconds) -> bool` (e.g. threading.Event).
    """
    last = path.stat().st_mtime if path.exists() else 0.0
    while not stop.wait(1.0):
        try:
            cur = path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            continue
        if cur != last:
            last = cur
            try:
                on_change()
            except Exception:
                log.exception("config reload handler raised")
