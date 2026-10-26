"""Parse keyboard/mouse chords and comma-separated macro sequences."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ._keycodes import KEY_CODE, MOUSE_CODE

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
    held_keys: tuple[str, ...] = ()
    hold_ms: int | None = None

    @property
    def keys(self) -> tuple[str, ...]:
        """Non-modifier keys/buttons held together, in press order."""
        return self.held_keys + (self.key,)

    def __str__(self) -> str:
        parts = list(self.modifiers) + list(self.keys)
        chord = "+".join(parts)
        return chord if self.hold_ms is None else f"{chord}@{self.hold_ms}"


@dataclass(frozen=True)
class ParsedWait:
    duration_ms: int

    def __str__(self) -> str:
        return f"wait:{self.duration_ms}"


class ShortcutParseError(ValueError):
    pass


MAX_DURATION_MS = 60_000


def _duration_ms(value: str) -> int:
    value = value.strip()
    if not re.fullmatch(r"[0-9]{1,5}", value) or int(value) > MAX_DURATION_MS:
        raise ShortcutParseError(
            f"duration must be an integer from 0 to {MAX_DURATION_MS} milliseconds: {value!r}"
        )
    return int(value)


def parse_shortcut(shortcut: str) -> ParsedShortcut:
    """Parse 'ctrl+shift+t' -> ParsedShortcut(('ctrl','shift'), 't').

    - Tokens are case-insensitive.
    - The final token is the keycap (letter, digit, named key like F1 / Home / Return).
    - Earlier tokens may be modifiers or keys/buttons held with the final key.
    """
    if not shortcut or not shortcut.strip():
        raise ShortcutParseError("empty shortcut")

    shortcut = shortcut.strip()
    hold_ms = None
    if "@" in shortcut:
        chord, _, duration = shortcut.rpartition("@")
        # Literal @ keycaps (ctrl+@, @+a) remain the shifted '2' key.
        literal_at = (
            (not chord.strip() or chord.rstrip().endswith("+"))
            and (not duration.strip() or duration.lstrip().startswith("+"))
        )
        if not literal_at:
            hold_ms = _duration_ms(duration)
            shortcut = chord.strip()
            if not shortcut:
                raise ShortcutParseError("hold duration requires a chord")

    tokens = [t.strip().lower() for t in shortcut.split("+") if t.strip()]
    if not tokens:
        raise ShortcutParseError(f"no tokens in {shortcut!r}")

    # Numbered names follow game conventions, not X11 wheel-button numbers.
    mouse_aliases = {
        "mouse1": "mouse_left", "mouse2": "mouse_right",
        "mouse3": "mouse_middle", "mouse4": "mouse_back",
        "mouse5": "mouse_forward",
    }
    tokens = [mouse_aliases.get(token, token) for token in tokens]
    key = tokens[-1]

    seen: list[str] = []
    held_keys: list[str] = []
    for token in tokens[:-1]:
        canonical = _MOD_ALIAS.get(token, token)
        if canonical in MODIFIERS:
            if canonical not in seen:
                seen.append(canonical)
        else:
            if canonical in _SHIFTED_SYMBOL:
                canonical = _SHIFTED_SYMBOL[canonical]
                if "shift" not in seen:
                    seen.append("shift")
            if canonical not in KEY_CODE and canonical not in MOUSE_CODE:
                raise ShortcutParseError(f"unknown key or modifier {token!r} in {shortcut!r}")
            if canonical not in held_keys:
                held_keys.append(canonical)

    if key in MODIFIERS:
        raise ShortcutParseError(f"shortcut {shortcut!r} has no non-modifier key")

    if key in _SHIFTED_SYMBOL:
        key = _SHIFTED_SYMBOL[key]
        if "shift" not in seen:
            seen.append("shift")

    return ParsedShortcut(
        modifiers=tuple(seen), key=key, held_keys=tuple(held_keys), hold_ms=hold_ms
    )


SHORTCUT_SEP = ","


def parse_shortcut_sequence(shortcut: str) -> list[ParsedShortcut | ParsedWait]:
    """Parse a shortcut that may contain multiple chords separated by SHORTCUT_SEP.

    Single chords like 'ctrl+t' return a one-element list (backward compatible
    with callers that only expect one chord).  Multi-chord shortcuts use ','
    as the delimiter, e.g. 'ctrl+b,shift+\\'' for a tmux prefix sequence.
    Optional @milliseconds holds a chord; wait:milliseconds pauses with all
    inputs released. Explicit waits replace the usual gap at that boundary.
    """
    parts = [p.strip() for p in shortcut.strip().split(SHORTCUT_SEP)]
    result: list[ParsedShortcut | ParsedWait] = []
    for i, part in enumerate(parts):
        if not part:
            raise ShortcutParseError(
                f"empty chord at position {i} in {shortcut!r}"
            )
        if part.lower().startswith("wait:"):
            result.append(ParsedWait(_duration_ms(part[5:])))
        else:
            result.append(parse_shortcut(part))
    return result
