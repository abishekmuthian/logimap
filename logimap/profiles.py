"""Profile and key-binding dataclasses; focus-to-profile resolver."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KEY_NAMES: tuple[str, ...] = (
    "GRID_0", "GRID_1", "GRID_2",
    "GRID_3", "GRID_4", "GRID_5",
    "GRID_6", "GRID_7", "GRID_8",
)


@dataclass(frozen=True)
class WindowFocus:
    wm_class: str
    resource_name: str
    caption: str
    pid: int | None = None


@dataclass
class KeyBinding:
    title: str = ""
    shortcut: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"title": self.title, "shortcut": self.shortcut}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "KeyBinding":
        return cls(
            title=str(data.get("title", "")),
            shortcut=str(data.get("shortcut", "")),
        )


@dataclass
class Match:
    wm_class: str = "*"
    title_regex: str | None = None

    def matches(self, focus: WindowFocus) -> bool:
        if self.wm_class != "*":
            if focus.wm_class.lower() != self.wm_class.lower():
                return False
        if self.title_regex:
            if not re.search(self.title_regex, focus.caption or "", re.IGNORECASE):
                return False
        return True

    def to_json(self) -> dict[str, Any]:
        return {"wm_class": self.wm_class, "title_regex": self.title_regex}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Match":
        return cls(
            wm_class=str(data.get("wm_class", "*")),
            title_regex=data.get("title_regex"),
        )


@dataclass
class Profile:
    name: str
    match: Match = field(default_factory=Match)
    bg_color: tuple[int, int, int] = (30, 30, 30)
    fg_color: tuple[int, int, int] = (255, 255, 255)
    keys: dict[str, KeyBinding] = field(default_factory=dict)
    extra_pages: list[dict[str, KeyBinding]] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return 1 + len(self.extra_pages)

    def page_keys(self, page: int = 0) -> dict[str, KeyBinding]:
        """Return a page's bindings; the existing keys field is page zero."""
        if not 0 <= page < self.page_count:
            raise IndexError(f"page {page} outside profile {self.name!r}")
        return self.keys if page == 0 else self.extra_pages[page - 1]

    def remove_page(self, page: int) -> None:
        if self.page_count == 1:
            raise ValueError("a profile must have at least one page")
        self.page_keys(page)  # validate before mutating
        if page == 0:
            self.keys = self.extra_pages.pop(0)
        else:
            self.extra_pages.pop(page - 1)

    def get(self, key_name: str, page: int = 0) -> KeyBinding | None:
        return self.page_keys(page).get(key_name)

    def to_json(self) -> dict[str, Any]:
        data = {
            "match": self.match.to_json(),
            "bg_color": list(self.bg_color),
            "fg_color": list(self.fg_color),
            "keys": {k: v.to_json() for k, v in self.keys.items()},
        }
        if self.extra_pages:
            data["extra_pages"] = [
                {k: v.to_json() for k, v in keys.items()}
                for keys in self.extra_pages
            ]
        return data

    @classmethod
    def from_json(cls, name: str, data: dict[str, Any]) -> "Profile":
        return cls(
            name=name,
            match=Match.from_json(data.get("match", {})),
            bg_color=tuple(data.get("bg_color", [30, 30, 30])),  # type: ignore[arg-type]
            fg_color=tuple(data.get("fg_color", [255, 255, 255])),  # type: ignore[arg-type]
            keys={
                k: KeyBinding.from_json(v)
                for k, v in (data.get("keys") or {}).items()
            },
            extra_pages=[
                {k: KeyBinding.from_json(v) for k, v in (keys or {}).items()}
                for keys in (data.get("extra_pages") or [])
            ],
        )


def resolve(profiles: dict[str, Profile], focus: WindowFocus, default_name: str) -> Profile:
    """Pick the first profile whose Match accepts this focus; fall back to default."""
    for p in profiles.values():
        if p.name == default_name:
            continue
        if p.match.matches(focus):
            return p
    return profiles.get(default_name) or Profile(name=default_name)
