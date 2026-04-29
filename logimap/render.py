"""Render a key title into a 90x90 JPEG suitable for MXKeypadDevice.set_key_image."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Hashable, Mapping, TypeVar

from PIL import Image, ImageDraw, ImageFont

KEY_SIZE = (90, 90)
JPEG_QUALITY = 85
MAX_LINES = 3
LINE_GAP = 3  # extra px between rendered lines
SIZES = (20, 18, 16, 14, 12, 11, 10, 9)

_FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font_path() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


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


def make_key_image(
    title: str,
    subtitle: str | None = None,
    bg: tuple[int, int, int] = (30, 30, 30),
    fg: tuple[int, int, int] = (255, 255, 255),
    accent: tuple[int, int, int] = (80, 160, 255),
    size: int | None = None,
) -> bytes:
    """Render title text into a 90x90 JPEG and return the bytes.

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
) -> dict[K, bytes]:
    """Render a set of keys at one shared font size for visual consistency.

    Picks the smallest size needed by any non-empty title in the set. Empty
    titles get a blank tile in the same `bg` color.
    """
    blank = make_blank(bg)
    nonempty = [t for t in titles.values() if t]
    if not nonempty:
        return {k: blank for k in titles}
    common_size = min(_pick_font_size(t) for t in nonempty)
    out: dict[K, bytes] = {}
    for key, title in titles.items():
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
