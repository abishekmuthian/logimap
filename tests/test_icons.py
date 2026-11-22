import shutil
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from logimap import icons, render
from logimap.render import make_profile_images

RED_CIRCLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
    '<circle cx="8" cy="8" r="8" fill="#ff0000"/></svg>'
)
WIDE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16" viewBox="0 0 32 16">'
    '<rect width="32" height="16" fill="#00ff00"/></svg>'
)


def _has_cairosvg() -> bool:
    try:
        import cairosvg  # noqa: F401
    except Exception:  # noqa: BLE001 - missing package or libcairo
        return False
    return True


HAS_RSVG = shutil.which("rsvg-convert") is not None
HAS_CAIROSVG = _has_cairosvg()
needs_svg = pytest.mark.skipif(
    not (HAS_RSVG or HAS_CAIROSVG), reason="no SVG rasterizer installed"
)


@pytest.fixture(autouse=True)
def _clear_caches():
    icons.clear_caches()
    yield
    icons.clear_caches()


@pytest.fixture
def fake_themes(tmp_path, monkeypatch):
    """Point theme lookup at an empty icons dir under tmp_path."""
    base = tmp_path / "icons"
    base.mkdir()
    monkeypatch.setattr(icons, "_base_dirs", lambda: [base])
    monkeypatch.setattr(icons, "_pixmap_dirs", lambda: [])

    def add(rel: str, content: str = RED_CIRCLE_SVG) -> Path:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".png":
            Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(p)
        else:
            p.write_text(content)
        return p

    return add


def _center(img: Image.Image) -> tuple[int, ...]:
    return img.getpixel((img.width // 2, img.height // 2))


@needs_svg
def test_svg_file_rasterized_to_box(tmp_path) -> None:
    svg = tmp_path / "dot.svg"
    svg.write_text(RED_CIRCLE_SVG)
    img = icons.load(str(svg), 88)
    assert img is not None and img.size == (88, 88)
    r, g, b, a = _center(img)
    assert r > 200 and g < 60 and a == 255
    assert img.getpixel((0, 0))[3] == 0  # transparent corner


@needs_svg
def test_svg_keeps_aspect_ratio(tmp_path) -> None:
    svg = tmp_path / "wide.svg"
    svg.write_text(WIDE_SVG)
    img = icons.load(str(svg), 80)
    assert img is not None
    # Either cropped to content (80x40) or padded with transparency.
    if img.size != (80, 40):
        assert img.getpixel((40, 5))[3] == 0


@pytest.mark.skipif(not HAS_CAIROSVG, reason="cairosvg not installed")
def test_svg_falls_back_to_cairosvg(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(icons.shutil, "which", lambda _name: None)
    svg = tmp_path / "dot.svg"
    svg.write_text(RED_CIRCLE_SVG)
    img = icons.load(str(svg), 64)
    assert img is not None
    assert _center(img)[0] > 200


def test_svg_without_rasterizer_returns_none(tmp_path, monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_cairosvg(name, *args, **kwargs):
        if name == "cairosvg":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(icons.shutil, "which", lambda _name: None)
    monkeypatch.setattr(builtins, "__import__", no_cairosvg)
    svg = tmp_path / "dot.svg"
    svg.write_text(RED_CIRCLE_SVG)
    assert icons.load(str(svg), 64) is None


@needs_svg
def test_svg_icon_key_renders(tmp_path) -> None:
    svg = tmp_path / "dot.svg"
    svg.write_text(RED_CIRCLE_SVG)
    imgs = make_profile_images({"a": ""}, icons={"a": str(svg)})
    px = Image.open(BytesIO(imgs["a"])).convert("RGB").getpixel((59, 59))
    assert px[0] > 200 and px[1] < 60


def test_theme_variant_follows_background(fake_themes) -> None:
    dark = fake_themes("breeze-dark/actions/22/media-playback-start.svg")
    light = fake_themes("breeze/actions/22/media-playback-start.svg")
    assert icons.resolve("media-playback-start", dark=True) == dark
    assert icons.resolve("media-playback-start", dark=False) == light


def test_prefers_largest_size(fake_themes) -> None:
    fake_themes("hicolor/16x16/apps/myapp.png")
    big = fake_themes("hicolor/128x128/apps/myapp.png")
    assert icons.resolve("myapp") == big


def test_scalable_beats_bitmaps(fake_themes) -> None:
    fake_themes("hicolor/256x256/apps/myapp.png")
    svg = fake_themes("hicolor/scalable/apps/myapp.svg")
    assert icons.resolve("myapp") == svg


def test_reverse_dns_app_id(fake_themes) -> None:
    found = fake_themes("hicolor/scalable/apps/com.example.Widget.svg")
    assert icons.resolve("widget") == found
    assert icons.resolve("com.example.Widget") == found


def test_scale_dirs_are_skipped(fake_themes) -> None:
    fake_themes("breeze/actions/22@2x/only-in-scaled.svg")
    assert icons.resolve("only-in-scaled") is None


def test_path_icons_are_not_cached(tmp_path) -> None:
    png = tmp_path / "later.png"
    assert icons.resolve(str(png)) is None
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(png)
    assert icons.resolve(str(png)) == png


def test_missing_icon_warns_once(fake_themes, caplog) -> None:
    with caplog.at_level("WARNING", logger="logimap.icons"):
        for _ in range(3):
            icons.load("no-such-icon-xyz", 64)
    assert sum("no-such-icon-xyz" in r.message for r in caplog.records) == 1


def test_unknown_icon_and_missing_path(fake_themes) -> None:
    assert icons.resolve("definitely-not-an-icon") is None
    assert icons.resolve("/nonexistent/icon.svg") is None
    assert icons.load("definitely-not-an-icon", 64) is None


def test_unknown_user_tilde_is_not_an_error() -> None:
    for icon in ("~l", "~nosuchuser-xyz", "~nosuchuser-xyz/x.png"):
        assert icons.resolve(icon) is None
        assert icons.load(icon, 64) is None
    imgs = make_profile_images({"a": "Hi"}, icons={"a": "~nosuchuser-xyz/x.png"})
    assert imgs["a"] == make_profile_images({"a": "Hi"})["a"]


def test_relative_paths_are_relative_to_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "pics").mkdir()
    png = tmp_path / "pics" / "a.png"
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(png)
    monkeypatch.chdir("/")
    assert icons.resolve("pics/a.png") == png
    assert icons.resolve("~/pics/a.png") == png


def _png_claiming_size(path: Path, width: int, height: int) -> None:
    """A tiny PNG whose header claims a huge size (a decompression bomb)."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b""))


def test_decompression_bomb_falls_back_to_text(tmp_path) -> None:
    png = tmp_path / "bomb.png"
    _png_claiming_size(png, 20000, 20000)
    with pytest.raises(Image.DecompressionBombError):
        Image.open(png)
    assert icons.load(str(png), 64) is None
    imgs = make_profile_images({"a": "Hi"}, icons={"a": str(png)})
    assert imgs["a"] == make_profile_images({"a": "Hi"})["a"]


def test_render_error_falls_back_to_text(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise ValueError("boom")

    monkeypatch.setattr(render, "make_icon_image", boom)
    imgs = make_profile_images({"a": "Hi", "b": ""}, icons={"a": "x", "b": "y"})
    assert imgs["a"] == make_profile_images({"a": "Hi"})["a"]
    assert imgs["b"] == render.make_blank((30, 30, 30))


@pytest.mark.skipif(not HAS_RSVG, reason="rsvg-convert not installed")
def test_rsvg_handles_dash_leading_filename(tmp_path, monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_cairosvg(name, *args, **kwargs):
        if name == "cairosvg":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cairosvg)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "-o.svg").write_text(RED_CIRCLE_SVG)
    img = icons._rasterize_svg(Path("-o.svg"), 32)
    assert img is not None and _center(img)[0] > 200


def test_clear_caches_finds_newly_installed_icons(fake_themes) -> None:
    assert icons.resolve("newapp") is None
    found = fake_themes("hicolor/scalable/apps/newapp.svg")
    assert icons.resolve("newapp") is None  # still cached
    icons.clear_caches()
    assert icons.resolve("newapp") == found


@pytest.mark.parametrize("title,max_lines", [
    ("Play", 1),
    ("Reopen Closed Tab", 2),
])
def test_icon_label_wraps_before_shrinking(title, max_lines) -> None:
    lines, font = render._layout_icon_label(title)
    assert len(lines) <= max_lines
    assert " ".join(lines) == title
    if hasattr(font, "size"):
        assert font.size >= 12


def test_icon_label_truncates_with_ellipsis() -> None:
    title = "This label is far too long to fit on a keypad key at any size"
    lines, font = render._layout_icon_label(title)
    assert len(lines) == 2
    assert lines[-1].endswith("…")
    assert all(font.getlength(line) <= render.KEY_SIZE[0] - 8 for line in lines)


def test_whitespace_title_uses_full_size_icon(tmp_path) -> None:
    png = tmp_path / "dot.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(png)
    assert render.make_icon_image(str(png), "   ") == render.make_icon_image(str(png), "")
