"""Resolve and rasterize key icons.

A key's ``icon`` is either a path to an image file (PNG, JPEG, SVG, ...)
or a freedesktop icon name such as ``firefox`` or ``media-playback-start``,
looked up in the installed icon themes (including Flatpak app icons). When
logimap runs inside a distrobox/toolbox container, the host's themes under
``/run/host`` are searched too.

SVGs are rasterized with ``rsvg-convert`` (librsvg) when it is installed,
then KDE's ``ksvgtopng``, then the optional ``cairosvg`` Python package.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Symbolic icons are drawn in a single colour, so pick the theme variant
# that contrasts with the key background.
_COMMON_THEMES = ("hicolor", "Adwaita", "AdwaitaLegacy", "oxygen")
DARK_BG_THEMES = ("breeze-dark", "breeze", *_COMMON_THEMES)
LIGHT_BG_THEMES = ("breeze", "breeze-dark", *_COMMON_THEMES)
IMAGE_EXTS = (".svg", ".png", ".xpm", ".jpg", ".jpeg", ".webp", ".gif")


def _base_dirs() -> list[Path]:
    home = Path.home()
    dirs = [
        home / ".local/share/icons",
        home / ".icons",
        Path("/usr/share/icons"),
        Path("/run/host/usr/share/icons"),
        home / ".local/share/flatpak/exports/share/icons",
        Path("/var/lib/flatpak/exports/share/icons"),
        Path("/run/host/var/lib/flatpak/exports/share/icons"),
    ]
    seen: set[Path] = set()
    out = []
    for d in dirs:
        try:
            real = d.resolve()
        except OSError:
            continue
        if d.is_dir() and real not in seen:
            seen.add(real)
            out.append(d)
    return out


def _pixmap_dirs() -> list[Path]:
    return [p for p in (Path("/usr/share/pixmaps"), Path("/run/host/usr/share/pixmaps")) if p.is_dir()]


_SIZE_RE = re.compile(r"/(\d+)(?:x\d+)?(?:@(\d)x)?/")


def _size_score(path: Path) -> tuple[int, int]:
    """Bigger is better. Prefer the largest size directory (small sizes are
    simplified, pixel-hinted drawings), then SVG over bitmaps."""
    s = str(path)
    is_svg = int(path.suffix.lower() == ".svg")
    if "/scalable/" in s:
        return (512, is_svg)
    m = _SIZE_RE.search(s)
    size = int(m.group(1)) * int(m.group(2) or 1) if m else 0
    if m and m.group(2):  # @2x/@3x are the same drawing as the base size
        size = int(m.group(1))
    return (size, is_svg)


@lru_cache(maxsize=None)
def _theme_index(theme_dir: str) -> dict[str, list[str]]:
    """Map icon name -> candidate file paths for one theme directory."""
    index: dict[str, list[str]] = {}
    for root, dirs, files in os.walk(theme_dir, followlinks=True):
        # Breeze's "16@2x"-style dirs are symlinks to the base size; skipping
        # them makes indexing ~3x faster without losing any names.
        dirs[:] = [d for d in dirs if "@" not in d]
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() in IMAGE_EXTS:
                index.setdefault(stem, []).append(os.path.join(root, f))
    return index


def resolve(icon: str, dark: bool = True) -> Path | None:
    """Return an image file for `icon` (a path or a theme icon name).

    `dark` means the icon will sit on a dark background, so light-on-dark
    theme variants are preferred.
    """
    icon = icon.strip()
    if not icon:
        return None
    if "/" in icon or Path(icon).suffix.lower() in IMAGE_EXTS:
        # Not cached: the file may be created or replaced while running.
        p = _expand_path(icon)
        return p if p is not None and p.is_file() else None
    return _resolve_name(icon, dark)


def _expand_path(icon: str) -> Path | None:
    """Expand ``~`` and anchor relative paths at $HOME, so the editor and the
    daemon (which may have different working directories) agree."""
    try:
        p = Path(icon).expanduser()
    except RuntimeError:  # "~nosuchuser/..."
        return None
    return p if p.is_absolute() else Path.home() / p


@lru_cache(maxsize=512)
def _resolve_name(icon: str, dark: bool) -> Path | None:
    themes = DARK_BG_THEMES if dark else LIGHT_BG_THEMES

    def lookup(paths_for) -> Path | None:
        for theme in themes:
            for base in _base_dirs():
                tdir = base / theme
                if not tdir.is_dir():
                    continue
                cands = [
                    Path(c) for c in paths_for(_theme_index(str(tdir)))
                    if os.path.exists(c)
                ]
                if cands:
                    return max(cands, key=_size_score)
        return None

    found = lookup(lambda index: index.get(icon, []))
    if found is None:
        # Flatpak/reverse-DNS app IDs: "firefox" -> org.mozilla.firefox,
        # "spotify" -> com.spotify.Client, "dolphin" -> org.kde.dolphin.
        low = icon.lower()
        found = lookup(lambda index: [
            c for name, paths in index.items()
            if "." in name and low in name.lower().split(".")[1:]
            for c in paths
        ])
    if found is not None:
        return found
    for d in _pixmap_dirs():
        for ext in IMAGE_EXTS:
            f = d / f"{icon}{ext}"
            if f.is_file():
                return f
    return None


@lru_cache(maxsize=256)
def _warn_missing(icon: str) -> None:
    """Log a missing icon once (per cache generation), not on every repaint."""
    log.warning("icon not found: %r", icon)


def clear_caches() -> None:
    """Forget theme indexes and lookups, e.g. after an app or icon theme was
    installed. The daemon calls this on every config reload."""
    _theme_index.cache_clear()
    _resolve_name.cache_clear()
    _warn_missing.cache_clear()
    _load_cached.cache_clear()


def _rasterize_svg(path: Path, size: int) -> Image.Image | None:
    exe = shutil.which("rsvg-convert")
    if exe:
        try:
            out = subprocess.run(
                [exe, "-w", str(size), "-h", str(size), "-a", str(path.absolute())],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=10,
            ).stdout
            return Image.open(BytesIO(out)).convert("RGBA")
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("rsvg-convert failed for %s: %s", path, e)
    exe = shutil.which("ksvgtopng")
    if exe:
        img = _ksvgtopng(exe, path, size)
        if img is not None:
            return img
    try:
        import cairosvg  # type: ignore[import-not-found]

        out = cairosvg.svg2png(url=str(path), output_width=size, output_height=size)
        return Image.open(BytesIO(out)).convert("RGBA")
    except Exception as e:  # noqa: BLE001 - optional dependency
        log.warning(
            "cannot rasterize SVG %s: install rsvg-convert (librsvg2-tools / "
            "librsvg2-bin / librsvg) or `pip install cairosvg`: %s", path, e
        )
    return None


def _svg_aspect(path: Path) -> float:
    """Width / height of an SVG from its viewBox or width/height; 1.0 if unknown."""
    def num(v: str | None) -> float | None:
        m = re.match(r"\s*([0-9.]+)", v or "")
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None

    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return 1.0
    box = (root.get("viewBox") or "").replace(",", " ").split()
    if len(box) == 4:
        w, h = num(box[2]), num(box[3])
    else:
        w, h = num(root.get("width")), num(root.get("height"))
    return w / h if w and h else 1.0


def _ksvgtopng(exe: str, path: Path, size: int) -> Image.Image | None:
    """Rasterize with KDE's ksvgtopng, which stretches to the size it is given,
    so pass the box scaled to the SVG's own aspect ratio."""
    aspect = _svg_aspect(path)
    w, h = (size, max(1, round(size / aspect))) if aspect >= 1 else (max(1, round(size * aspect)), size)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    with tempfile.TemporaryDirectory(prefix="logimap-svg-") as tmp:
        out = Path(tmp) / "icon.png"
        try:
            subprocess.run(
                [exe, str(w), str(h), str(path.absolute()), str(out)],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=10, env=env,
            )
            with Image.open(out) as img:
                return img.convert("RGBA")
        except (subprocess.SubprocessError, OSError) as e:
            log.warning("ksvgtopng failed for %s: %s", path, e)
    return None


@lru_cache(maxsize=256)
def _load_cached(path: str, mtime: float, size: int) -> Image.Image | None:
    p = Path(path)
    if p.suffix.lower() == ".svg":
        img = _rasterize_svg(p, size)
    else:
        try:
            img = Image.open(p)
            img.load()
            img = img.convert("RGBA")
        except Exception as e:  # noqa: BLE001 - OSError, DecompressionBombError, ...
            log.warning("cannot open icon %s: %s", p, e)
            return None
    if img is None:
        return None
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    if max(img.size) < size:  # upscale small bitmaps to fill the box
        scale = size / max(img.size)
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return img


def load(icon: str, size: int, *, dark: bool = True) -> Image.Image | None:
    """Load `icon` as an RGBA image that fits in a `size`x`size` box."""
    path = resolve(icon, dark)
    if path is None:
        if icon.strip():
            _warn_missing(icon.strip())
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    img = _load_cached(str(path), mtime, size)
    return img.copy() if img is not None else None
