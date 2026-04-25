from logimap.render import KEY_SIZE, make_blank, make_key_image


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
