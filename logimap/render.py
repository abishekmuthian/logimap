"""Render a key title into an MX Keypad-sized JPEG."""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Hashable, Mapping, TypeVar

import logging

from PIL import Image, ImageDraw, ImageFont

from . import icons as _icons

_log = logging.getLogger(__name__)

# The native driver programs each key's destination rectangle as 118x118.
# JPEGs are not scaled by the device, so smaller images only fill the
# destination's upper-left corner.
KEY_SIZE = (118, 118)
JPEG_QUALITY = 85
MAX_LINES = 3
LINE_GAP = 3  # extra px between rendered lines
SIZES = (20, 18, 16, 14, 12, 11, 10, 9)

_FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return _fc_match("DejaVu Sans:style=Bold")


def _fc_match(pattern: str) -> str | None:
    """Ask fontconfig for the closest font file, e.g. a user-installed copy
    under ~/.local/share/fonts or a stand-in bold sans."""
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-f", "%{file}", pattern],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    return out if out and Path(out).is_file() else None


def _wrap(
    text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> tuple[list[str], bool]:
    """Greedy word-wrap that falls back to character-wrap for long words.

    Returns (lines, had_to_char_wrap). The flag lets callers reject layouts
    that broke a word mid-character so they can try a smaller font first.
    """
    words = text.split()
    lines: list[str] = []
    cur = ""
    had_to_char_wrap = False
    for word in words:
        candidate = f"{cur} {word}".strip()
        if font.getlength(candidate) <= max_width:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
        if font.getlength(word) <= max_width:
            cur = word
        else:
            had_to_char_wrap = True
            buf = ""
            for ch in word:
                if font.getlength(buf + ch) > max_width:
                    lines.append(buf)
                    buf = ch
                else:
                    buf += ch
            cur = buf
    if cur:
        lines.append(cur)
    return lines, had_to_char_wrap


def _pick_font_size(title: str, *, subtitle: str | None = None) -> int:
    """Largest size at which `title` fits in 3 lines without char-wrap.

    Falls back to the smallest configured size if no clean layout exists.
    """
    font_path = _font_path()
    if not font_path:
        return SIZES[0]
    padding = 6
    max_width = KEY_SIZE[0] - 2 * padding
    max_h = KEY_SIZE[1] - 2 * padding - (14 if subtitle else 0)
    for size in SIZES:
        font = ImageFont.truetype(font_path, size)
        lines, had_to_char_wrap = _wrap(title or "", font, max_width)
        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        n = len(lines)
        total_h = line_h * n + LINE_GAP * max(0, n - 1)
        if n <= MAX_LINES and total_h <= max_h and not had_to_char_wrap:
            return size
    return SIZES[-1]


ICON_ONLY_SIZE = 88
ICON_WITH_LABEL_SIZE = 70
ICON_LABEL_SIZES = (15, 14, 13, 12, 11, 10, 9)
ICON_LABEL_MAX_LINES = 2
ELLIPSIS = "…"


def _is_dark(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def _truncate(lines: list[str], font, max_width: int, n: int) -> list[str]:
    """Keep the first `n` lines, ending the last with an ellipsis if cut."""
    if len(lines) <= n:
        return lines
    kept = lines[:n]
    last = kept[-1]
    while last and font.getlength(last + ELLIPSIS) > max_width:
        last = last[:-1]
    kept[-1] = last.rstrip() + ELLIPSIS
    return kept


def _encode(img: Image.Image) -> bytes:
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def _layout_icon_label(title: str) -> tuple[list[str], ImageFont.ImageFont]:
    """Wrap an icon label: the largest size at which it fits in two lines
    without breaking a word, else the smallest size cut with an ellipsis."""
    font_path = _font_path()
    max_width = KEY_SIZE[0] - 8
    for sz in ICON_LABEL_SIZES:
        font = ImageFont.truetype(font_path, sz) if font_path else ImageFont.load_default()
        lines, char_wrapped = _wrap(title, font, max_width)
        if len(lines) <= ICON_LABEL_MAX_LINES and not char_wrapped:
            return lines, font
    return _truncate(lines, font, max_width, ICON_LABEL_MAX_LINES), font


def make_icon_image(
    icon: str,
    title: str = "",
    bg: tuple[int, int, int] = (30, 30, 30),
    fg: tuple[int, int, int] = (255, 255, 255),
) -> bytes | None:
    """Render an icon (optionally with a one/two-line label under it).

    Returns None if the icon can't be found or decoded, so callers can fall
    back to a text-only key.
    """
    title = title.strip()
    box = ICON_WITH_LABEL_SIZE if title else ICON_ONLY_SIZE
    icon_img = _icons.load(icon, box, dark=_is_dark(bg))
    if icon_img is None:
        return None
    img = Image.new("RGB", KEY_SIZE, color=bg)
    draw = ImageDraw.Draw(img)

    label_lines: list[str] = []
    label_font = None
    line_h = 0
    if title:
        label_lines, label_font = _layout_icon_label(title)
        line_h = label_font.getbbox("Ag")[3] - label_font.getbbox("Ag")[1]

    label_h = line_h * len(label_lines) + LINE_GAP * max(0, len(label_lines) - 1)
    gap = 6 if label_lines else 0
    # Lay out against the full square box, not the icon's own height, so a
    # wide icon (e.g. 70x53) is centred in its slot and its label lines up
    # with the labels on square-icon keys.
    total_h = box + gap + label_h
    y = (KEY_SIZE[1] - total_h) // 2
    x = (KEY_SIZE[0] - icon_img.width) // 2
    img.paste(icon_img, (x, y + (box - icon_img.height) // 2), icon_img)
    y += box + gap
    for line in label_lines:
        w = label_font.getlength(line)
        draw.text(((KEY_SIZE[0] - w) // 2, y), line, font=label_font, fill=fg)
        y += line_h + LINE_GAP
    return _encode(img)


def make_key_image(
    title: str,
    subtitle: str | None = None,
    bg: tuple[int, int, int] = (30, 30, 30),
    fg: tuple[int, int, int] = (255, 255, 255),
    accent: tuple[int, int, int] = (80, 160, 255),
    size: int | None = None,
) -> bytes:
    """Render title text into a 118x118 JPEG and return the bytes.

    If `size` is given, render at that exact font size — useful for keeping
    a row/grid of keys visually consistent. Otherwise auto-pick the largest
    size that fits cleanly.
    """
    img = Image.new("RGB", KEY_SIZE, color=bg)
    draw = ImageDraw.Draw(img)

    font_path = _font_path()
    padding = 6
    max_width = KEY_SIZE[0] - 2 * padding

    title_font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    if size is None:
        size = _pick_font_size(title, subtitle=subtitle)
    if font_path:
        title_font = ImageFont.truetype(font_path, size)
    else:
        title_font = ImageFont.load_default()
    title_lines, _ = _wrap(title or "", title_font, max_width)

    line_h = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
    n = len(title_lines)
    block_h = line_h * n + LINE_GAP * max(0, n - 1)
    y = (KEY_SIZE[1] - block_h) // 2
    if subtitle:
        y -= 8

    for line in title_lines:
        w = title_font.getlength(line)
        x = (KEY_SIZE[0] - w) // 2
        draw.text((x, y), line, font=title_font, fill=fg)
        y += line_h + LINE_GAP

    if subtitle:
        if font_path:
            sub_font = ImageFont.truetype(font_path, 10)
        else:
            sub_font = ImageFont.load_default()
        w = sub_font.getlength(subtitle)
        x = (KEY_SIZE[0] - w) // 2
        draw.text((x, KEY_SIZE[1] - 16), subtitle, font=sub_font, fill=accent)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


K = TypeVar("K", bound=Hashable)


def make_profile_images(
    titles: Mapping[K, str],
    *,
    bg: tuple[int, int, int] = (30, 30, 30),
    fg: tuple[int, int, int] = (255, 255, 255),
    icons: Mapping[K, str] | None = None,
) -> dict[K, bytes]:
    """Render a set of keys at one shared font size for visual consistency.

    Picks the smallest size needed by any non-empty, text-only title in the
    set. Keys with a resolvable entry in `icons` are drawn as icons (with
    their title as a small label). Empty keys get a blank tile in `bg`.
    """
    icons = icons or {}
    blank = make_blank(bg)
    out: dict[K, bytes] = {}
    for key, title in titles.items():
        icon = icons.get(key) or ""
        if icon:
            try:
                rendered = make_icon_image(icon, title, bg=bg, fg=fg)
            except Exception:  # a broken icon must never stop painting
                _log.exception("cannot render icon %r; using its title", icon)
                rendered = None
            if rendered is not None:
                out[key] = rendered
    nonempty = [t for k, t in titles.items() if t and k not in out]
    common_size = min((_pick_font_size(t) for t in nonempty), default=SIZES[0])
    for key, title in titles.items():
        if key in out:
            continue
        if title:
            out[key] = make_key_image(title, bg=bg, fg=fg, size=common_size)
        else:
            out[key] = blank
    return out


def make_blank(bg: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    img = Image.new("RGB", KEY_SIZE, color=bg)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()
