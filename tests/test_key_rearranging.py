"""Drag gestures and binding preservation without a display or hardware."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from logimap.config import Config
from logimap.gui.app import LogimapApp
from logimap.gui.keypad_grid import KeypadGrid
from logimap.profiles import KEY_NAMES, KeyBinding, Profile


@pytest.fixture
def editor(tmp_path):
    app = LogimapApp.__new__(LogimapApp)
    profile = Profile(
        "default",
        keys={"GRID_0": KeyBinding("Page one", "ctrl+a")},
        extra_pages=[{
            "GRID_0": KeyBinding("Combo", "s+w+mouse_right@500,wait:300,mouse_left"),
            "GRID_1": KeyBinding("Paste", "ctrl+v"),
        }],
    )
    app.config = Config(profiles={"default": profile}, path=tmp_path / "profiles.json")
    app.current_profile_name = "default"
    app.current_page = 1
    app.grid = Mock()
    app.grid.select.side_effect = app._on_key_select
    app.title_var = Mock()
    app.title_var.set.side_effect = lambda _: app._title_changed()
    app.shortcut_widget = Mock()
    app.selected_key_label = Mock()
    app._set_key_enabled = Mock()
    app._set_status = Mock()
    return app


@pytest.mark.parametrize("target", ["GRID_1", "GRID_8"])
def test_rearrange_preserves_bindings_other_pages_and_saved_config(editor, target):
    profile = editor._current()
    before = profile.page_keys(1).copy()
    editor._reorder_keys("GRID_0", target)
    assert profile.get(target, 1) is before["GRID_0"]
    assert profile.get("GRID_0", 1) is before.get(target)
    assert profile.keys == {"GRID_0": KeyBinding("Page one", "ctrl+a")}
    assert len(profile.page_keys(1)) == len(before)
    editor.grid.select.assert_called_once_with(target)
    editor.title_var.set.assert_called_once_with(before["GRID_0"].title)
    editor.shortcut_widget.set.assert_called_once_with(before["GRID_0"].shortcut)
    editor.config.save()
    loaded = Config.load(editor.config.path).profiles["default"]
    assert loaded.to_json() == profile.to_json()


def test_drag_empty_cell_swaps_without_losing_destination(editor):
    binding = editor._current().get("GRID_1", 1)
    editor._reorder_keys("GRID_8", "GRID_1")
    assert editor._current().get("GRID_8", 1) is binding
    assert "GRID_1" not in editor._current().page_keys(1)


@pytest.mark.parametrize("source,target", [
    ("GRID_0", "GRID_0"), ("GRID_7", "GRID_8"),
    ("P1_LEFT", "GRID_0"), ("GRID_0", "invalid"),
])
def test_no_op_drops_leave_layout_alone(editor, source, target):
    before = editor._current().to_json()
    editor._reorder_keys(source, target)
    assert editor._current().to_json() == before
    editor.grid.render_profile.assert_not_called()
    editor._set_status.assert_not_called()


@pytest.fixture
def grid():
    widget = KeypadGrid.__new__(KeypadGrid)
    widget._on_select = Mock()
    widget._on_reorder = Mock()
    widget._selected = None
    widget._labels = {
        name: SimpleNamespace(configure=Mock(), master=Mock()) for name in KEY_NAMES
    }
    widget.focus_set = Mock()
    widget.winfo_containing = Mock(return_value=None)
    widget._cancel_drag()
    return widget


def event(x=100, y=100):
    return SimpleNamespace(x_root=x, y_root=y)


def test_drag_reports_source_and_actual_release_cell(grid):
    grid._on_press(event(), "GRID_0")
    grid._on_select.assert_called_once_with("GRID_0")
    grid.winfo_containing.return_value = grid._labels["GRID_1"]
    grid._on_motion(event(200))
    assert grid._drop_target == "GRID_1"
    grid._labels["GRID_1"].master.configure.assert_called_with(relief="raised", borderwidth=4)
    # Release over a different cell's border: use the release position.
    grid.winfo_containing.return_value = grid._labels["GRID_8"].master
    grid._on_release(event(300))
    grid._on_reorder.assert_called_once_with("GRID_0", "GRID_8")
    assert grid._drag_source is None
    assert grid._drop_target is None


@pytest.mark.parametrize("cancel", ["click", "same", "outside", "escape", "focus", "page"])
def test_clicks_and_cancelled_drags_do_not_rearrange(grid, cancel, monkeypatch):
    grid._on_press(event(), "GRID_0")
    if cancel == "click":
        grid.winfo_containing.return_value = grid._labels["GRID_1"]
        grid._on_motion(event(102))  # Too little movement to start dragging.
    else:
        grid.winfo_containing.return_value = grid._labels["GRID_1"]
        grid._on_motion(event(200))
        if cancel == "same":
            grid.winfo_containing.return_value = grid._labels["GRID_0"]
        elif cancel == "outside":
            grid.winfo_containing.return_value = None
        elif cancel in ("escape", "focus"):
            grid._cancel_drag(event())
        elif cancel == "page":
            monkeypatch.setattr("logimap.gui.keypad_grid.ImageTk", None)
            grid._render_text_only = Mock()
            grid.render_profile(Profile("next page"))
    grid._on_release(event(200))
    grid._on_reorder.assert_not_called()
    assert grid.selected() == "GRID_0"
    assert grid._drag_source is None
