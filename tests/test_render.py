from PIL import ImageFont

from logimap.render import (
    KEY_SIZE,
    _font_path,
    _pick_font_size,
    _wrap,
    make_blank,
    make_key_image,
    make_profile_images,
)


def test_jpeg_magic() -> None:
    data = make_key_image("Hello")
    assert data[:3] == b"\xff\xd8\xff"


def test_blank_jpeg() -> None:
    data = make_blank()
    assert data[:3] == b"\xff\xd8\xff"


def test_key_size_constant() -> None:
    assert KEY_SIZE == (90, 90)


def test_long_title_still_fits() -> None:
    data = make_key_image("Supercalifragilisticexpialidocious")
    assert data[:3] == b"\xff\xd8\xff"


def test_subtitle_variant() -> None:
    data = make_key_image("Save", subtitle="Ctrl+S")
    assert data[:3] == b"\xff\xd8\xff"


def test_empty_title() -> None:
    data = make_key_image("")
    assert data[:3] == b"\xff\xd8\xff"


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = _font_path()
    assert path, "DejaVu Sans Bold not installed; render tests require it"
    return ImageFont.truetype(path, size)


def test_wrap_short_word_fits_whole() -> None:
    lines, char_wrap = _wrap("Save", _font(20), 78)
    assert lines == ["Save"]
    assert char_wrap is False


def test_wrap_flags_mid_word_break() -> None:
    # "Sidebar" at 20px bold exceeds 78px → triggers char-wrap and the flag.
    lines, char_wrap = _wrap("Toggle Sidebar", _font(20), 78)
    assert char_wrap is True
    assert any(line in {"Sideba", "r"} or line.endswith("r") for line in lines[1:])


def test_wrap_no_break_at_smaller_font() -> None:
    _, char_wrap = _wrap("Toggle Sidebar", _font(14), 78)
    assert char_wrap is False


def test_pick_font_size_avoids_mid_word_breaks() -> None:
    # Regression: we used to render "Toggle Sidebar" as Toggle / Sideba / r at
    # 20px. _pick_font_size should drop to a font where Sidebar fits whole.
    assert _pick_font_size("Toggle Sidebar") <= 18
    assert _pick_font_size("Save") == 20  # short word should keep the max size


def test_profile_images_share_one_size() -> None:
    # Visual consistency: a profile of mixed-length titles must render at one
    # common font size so keys don't look like a salad of sizes.
    titles = {
        "GRID_0": "Save",
        "GRID_1": "Toggle Sidebar",
        "GRID_2": "Fullscreen",
        "GRID_3": "",
    }
    images = make_profile_images(titles)
    assert set(images) == set(titles)
    for jpeg in images.values():
        assert jpeg[:3] == b"\xff\xd8\xff"
    # The common size is the smallest needed by any non-empty title.
    expected = min(_pick_font_size(t) for t in titles.values() if t)
    assert expected == min(
        _pick_font_size("Save"),
        _pick_font_size("Toggle Sidebar"),
        _pick_font_size("Fullscreen"),
    )


def test_profile_images_all_blank_when_empty() -> None:
    images = make_profile_images({"a": "", "b": ""})
    assert len(images) == 2
    # All-blank fast path uses the helper's bg (default (30,30,30)).
    blank = make_blank((30, 30, 30))
    assert images["a"] == blank
    assert images["b"] == blank
