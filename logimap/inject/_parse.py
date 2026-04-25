"""Parse shortcut strings like 'ctrl+shift+t' into (modifiers, key)."""

from __future__ import annotations

from dataclasses import dataclass

MODIFIERS: set[str] = {"ctrl", "control", "shift", "alt", "meta", "super", "logo"}

_MOD_ALIAS = {
    "control": "ctrl",
    "super": "logo",
    "meta": "logo",
}


@dataclass(frozen=True)
class ParsedShortcut:
    modifiers: tuple[str, ...]
    key: str

    def __str__(self) -> str:
        parts = list(self.modifiers) + [self.key]
        return "+".join(parts)


class ShortcutParseError(ValueError):
    pass


def parse_shortcut(shortcut: str) -> ParsedShortcut:
    """Parse 'ctrl+shift+t' -> ParsedShortcut(('ctrl','shift'), 't').

    - Tokens are case-insensitive.
    - The final token is the keycap (letter, digit, named key like F1 / Home / Return).
    - Everything else must be a recognised modifier.
    """
    if not shortcut or not shortcut.strip():
        raise ShortcutParseError("empty shortcut")

    tokens = [t.strip().lower() for t in shortcut.split("+") if t.strip()]
    if not tokens:
        raise ShortcutParseError(f"no tokens in {shortcut!r}")

    key = tokens[-1]
    mod_tokens = tokens[:-1]

    seen: list[str] = []
    for m in mod_tokens:
        canonical = _MOD_ALIAS.get(m, m)
        if canonical not in MODIFIERS and canonical != "logo":
            raise ShortcutParseError(f"unknown modifier {m!r} in {shortcut!r}")
        if canonical in seen:
            continue
        seen.append(canonical)

    if key in MODIFIERS:
        raise ShortcutParseError(f"shortcut {shortcut!r} has no non-modifier key")

    return ParsedShortcut(modifiers=tuple(seen), key=key)
