"""Render a key title into a 90x90 JPEG suitable for MXKeypadDevice.set_key_image."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KEY_SIZE = (90, 90)
JPEG_QUALITY = 85
MAX_LINES = 3

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


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word-wrap that falls back to character-wrap for long words."""
    words = text.split()
    lines: list[str] = []
    cur = ""
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
    return lines


def make_key_image(
    title: str,
    subtitle: str | None = None,
    bg: tuple[int, int, int] = (30, 30, 30),
    fg: tuple[int, int, int] = (255, 255, 255),
    accent: tuple[int, int, int] = (80, 160, 255),
) -> bytes:
    """Render title text into a 90x90 JPEG and return the bytes."""
    img = Image.new("RGB", KEY_SIZE, color=bg)
    draw = ImageDraw.Draw(img)

    font_path = _font_path()
    padding = 6
    max_width = KEY_SIZE[0] - 2 * padding

    title_lines: list[str] = []
    title_font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    for size in (20, 18, 16, 14, 12, 11, 10, 9):
        if font_path:
            title_font = ImageFont.truetype(font_path, size)
        else:
            title_font = ImageFont.load_default()
        title_lines = _wrap(title or "", title_font, max_width)
        line_h = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
        total_h = line_h * len(title_lines)
        if len(title_lines) <= MAX_LINES and total_h <= KEY_SIZE[1] - 2 * padding - (14 if subtitle else 0):
            break
        if not font_path:
            break

    line_h = title_font.getbbox("Ag")[3] - title_font.getbbox("Ag")[1]
    block_h = line_h * len(title_lines)
    y = (KEY_SIZE[1] - block_h) // 2
    if subtitle:
        y -= 8

    for line in title_lines:
        w = title_font.getlength(line)
        x = (KEY_SIZE[0] - w) // 2
        draw.text((x, y), line, font=title_font, fill=fg)
        y += line_h

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


def make_blank(bg: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    img = Image.new("RGB", KEY_SIZE, color=bg)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()
