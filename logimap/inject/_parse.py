"""Parse shortcut strings like 'ctrl+shift+t' into (modifiers, key)."""

from __future__ import annotations

from dataclasses import dataclass

MODIFIERS: set[str] = {"ctrl", "control", "shift", "alt", "meta", "super", "logo"}

_MOD_ALIAS = {
    "control": "ctrl",
    "super": "logo",
    "meta": "logo",
}

# US-keyboard shifted symbols → (base_keycap, requires shift). A user typing
# `ctrl+?` means Ctrl+Shift+/, but `?` is not a real keycap and has no
# input-event keycode — translate at parse time so both uinput and wtype see
# only real keycaps and a clean modifier set.
_SHIFTED_SYMBOL: dict[str, str] = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
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

    if key in _SHIFTED_SYMBOL:
        key = _SHIFTED_SYMBOL[key]
        if "shift" not in seen:
            seen.append("shift")

    return ParsedShortcut(modifiers=tuple(seen), key=key)


SHORTCUT_SEP = ","


def parse_shortcut_sequence(shortcut: str) -> list[ParsedShortcut]:
    """Parse a shortcut that may contain multiple chords separated by SHORTCUT_SEP.

    Single chords like 'ctrl+t' return a one-element list (backward compatible
    with callers that only expect one chord).  Multi-chord shortcuts use ','
    as the delimiter, e.g. 'ctrl+b,shift+\\'' for a tmux prefix sequence.
    """
    shortcut = shortcut.strip()
    if SHORTCUT_SEP not in shortcut:
        return [parse_shortcut(shortcut)]
    parts = [p.strip() for p in shortcut.split(SHORTCUT_SEP)]
    if not parts:
        raise ShortcutParseError(f"empty shortcut {shortcut!r}")
    result: list[ParsedShortcut] = []
    for i, part in enumerate(parts):
        if not part:
            raise ShortcutParseError(
                f"empty chord at position {i} in {shortcut!r}"
            )
        result.append(parse_shortcut(part))
    return result
