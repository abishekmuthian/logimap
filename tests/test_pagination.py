"""Pagination without physical hardware or a display server."""

import importlib.util
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from logimap.config import Config
from logimap.gui.app import LogimapApp
from logimap.profiles import KEY_NAMES, KeyBinding, Match, Profile, WindowFocus


def paged_profile(name="default"):
    return Profile(
        name=name,
        keys={"GRID_0": KeyBinding("First", "ctrl+a")},
        extra_pages=[
            {"GRID_0": KeyBinding("Second", "s+w+mouse_right")},
            {},
        ],
    )


def flush_paint(app):
    """Run one iteration of the actual repaint worker without waiting."""
    with patch.object(app, "_stop") as stop:
        stop.is_set.side_effect = [False, False, True]
        app._paint_requested.set()
        app._retry_paint()


def test_legacy_profile_stays_on_first_page():
    data = {"keys": {"GRID_0": {"title": "Copy", "shortcut": "ctrl+c"}}}
    profile = Profile.from_json("legacy", data)
    assert profile.page_count == 1
    assert profile.page_keys() is profile.keys
    assert profile.get("GRID_0").shortcut == "ctrl+c"
    assert "extra_pages" not in profile.to_json()


def test_all_pages_roundtrip_and_duplicate_independently(tmp_path):
    cfg = Config(path=tmp_path / "profiles.json", profiles={"default": paged_profile()})
    cfg.save()
    profile = Config.load(cfg.path).profiles["default"]
    assert profile.page_count == 3
    assert profile.get("GRID_0", 1).shortcut == "s+w+mouse_right"
    assert profile.page_keys(2) == {}
    copy = Profile.from_json("copy", profile.to_json())
    copy.get("GRID_0", 1).title = "Changed"
    copy.keys.clear()
    assert profile.get("GRID_0", 1).title == "Second"
    assert profile.get("GRID_0").title == "First"


@pytest.mark.parametrize("page", [-1, 3])
def test_invalid_page_is_rejected(page):
    with pytest.raises(IndexError):
        paged_profile().page_keys(page)


@pytest.mark.parametrize("page", [0, 1, 2])
def test_remove_page_preserves_other_pages(page):
    profile = paged_profile()
    expected = [profile.page_keys(i) for i in range(3)]
    expected.pop(page)
    profile.remove_page(page)
    assert profile.page_count == 2
    assert [profile.page_keys(i) for i in range(2)] == expected


def test_cannot_remove_last_page():
    with pytest.raises(ValueError):
        Profile("default").remove_page(0)


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    # Load the real device and daemon with a fake SDK so this suite can run
    # without the compiled extension, USB hardware, or a session bus.
    sdk = ModuleType("logilinux")
    sdk.MXKeypadButton = Enum("MXKeypadButton", {
        **{name: i for i, name in enumerate(KEY_NAMES)},
        "P1_LEFT": 0xA1, "P2_RIGHT": 0xA2,
    })

    class ButtonEvent:
        def __init__(self, button, pressed=True):
            self.button = button
            self.pressed = pressed

        def get_mx_keypad_button(self):
            return self.button

    sdk.ButtonEvent = ButtonEvent
    sdk.DeviceType = SimpleNamespace(MX_KEYPAD="keypad")
    sdk.Library = Mock()
    sdk.MXKeypadDevice = Mock()
    monkeypatch.setitem(sys.modules, "logilinux", sdk)

    def load_module(name):
        path = Path(__file__).parents[1] / "logimap" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"logimap.{name}", path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        return module

    device = load_module("device")
    daemon = load_module("daemon")
    cfg = Config(path=tmp_path / "profiles.json", profiles={"default": paged_profile()})
    loader = Mock(return_value=cfg)
    monkeypatch.setattr(daemon, "Config", SimpleNamespace(load=loader))
    handle = Mock()
    handle.paint_grid.return_value = True
    monkeypatch.setattr(daemon, "KeypadHandle", Mock(return_value=handle))
    monkeypatch.setattr(daemon, "get_injector", Mock(return_value=Mock()))
    monkeypatch.setattr(daemon, "KWinFocusSource", Mock())
    monkeypatch.setattr(daemon.render, "make_profile_images", Mock(side_effect=lambda titles, **_: titles))
    app = daemon.Daemon()
    app._on_focus(WindowFocus("unknown", "", ""))
    return SimpleNamespace(
        app=app, cfg=cfg, handle=handle, buttons=sdk.MXKeypadButton,
        loader=loader, device=device, sdk=sdk,
    )


def test_next_previous_wrap_and_fire_current_page(runtime):
    app, buttons = runtime.app, runtime.buttons
    app._on_button(buttons.GRID_0)
    app._injector.press.assert_called_once_with("ctrl+a")
    app._injector.reset_mock()
    app._on_button(buttons.P2_RIGHT)
    flush_paint(app)
    images = runtime.handle.paint_grid.call_args.args[0]
    assert images[buttons.GRID_0] == "Second"
    assert len(images) == 9
    assert images[buttons.GRID_1] == ""
    app._on_button(buttons.GRID_0)
    app._injector.press.assert_called_once_with("s+w+mouse_right")
    app._injector.reset_mock()
    app._on_button(buttons.P2_RIGHT)
    flush_paint(app)
    app._on_button(buttons.GRID_0)  # Empty third page.
    assert set(runtime.handle.paint_grid.call_args.args[0].values()) == {""}
    app._on_button(buttons.P2_RIGHT)
    assert app._page == 0
    app._on_button(buttons.P1_LEFT)
    assert app._page == 2
    app._injector.press.assert_not_called()


def test_navigation_before_focus_and_single_page_do_not_inject(runtime):
    app, buttons = runtime.app, runtime.buttons
    app._current = None
    app._on_button(buttons.P2_RIGHT)
    app._current = Profile("default", keys={"P2_RIGHT": KeyBinding("", "ctrl+a")})
    runtime.handle.reset_mock()
    app._on_button(buttons.P2_RIGHT)
    app._on_button(buttons.P1_LEFT)
    runtime.handle.paint_grid.assert_not_called()
    app._injector.press.assert_not_called()


def test_page_remembered_per_profile_and_same_focus_does_not_repaint(runtime):
    app, buttons = runtime.app, runtime.buttons
    runtime.cfg.profiles["editor"] = paged_profile("editor")
    runtime.cfg.profiles["editor"].match = Match(wm_class="editor")
    app._on_button(buttons.P2_RIGHT)
    flush_paint(app)
    runtime.handle.reset_mock()
    app._on_focus(WindowFocus("unknown", "", "new title"))
    runtime.handle.paint_grid.assert_not_called()
    app._on_focus(WindowFocus("editor", "", ""))
    assert app._page == 0
    app._on_button(buttons.P1_LEFT)
    app._on_focus(WindowFocus("unknown", "", ""))
    assert app._page == 1
    app._on_focus(WindowFocus("editor", "", ""))
    assert app._page == 2


def test_reload_repaints_updated_page_and_clamps_removed_pages(runtime):
    app, buttons = runtime.app, runtime.buttons
    app._on_button(buttons.P2_RIGHT)
    updated = paged_profile()
    updated.get("GRID_0", 1).title = "Updated"
    runtime.loader.return_value = Config(profiles={"default": updated})
    app._reload()
    assert app._page == 1
    assert runtime.handle.paint_grid.call_args.args[0][buttons.GRID_0] == "Updated"
    runtime.loader.return_value = Config(profiles={"default": Profile("default")})
    app._reload()
    assert app._page == 0
    app._on_button(buttons.GRID_0)
    app._injector.press.assert_not_called()


def test_retry_uses_latest_page_after_failed_paint(runtime):
    app, buttons = runtime.app, runtime.buttons
    runtime.handle.paint_grid.return_value = False
    app._on_button(buttons.P2_RIGHT)
    flush_paint(app)
    assert app._pending_profile is app._current
    app._on_button(buttons.P2_RIGHT)
    assert app._page == 2
    runtime.handle.paint_grid.return_value = True
    flush_paint(app)
    assert app._pending_profile is None
    assert set(runtime.handle.paint_grid.call_args.args[0].values()) == {""}


def test_reconnect_repaints_selected_page(runtime):
    app, buttons = runtime.app, runtime.buttons
    app._on_button(buttons.P2_RIGHT)
    runtime.handle.reset_mock()
    runtime.handle.is_monitoring.return_value = False
    flush_paint(app)
    assert runtime.handle.paint_grid.call_args.args[0][buttons.GRID_0] == "Second"


def test_pending_page_is_replaced_when_profile_changes(runtime):
    runtime.app._on_button(runtime.buttons.P2_RIGHT)
    runtime.cfg.profiles["editor"] = Profile("editor", match=Match(wm_class="editor"))
    runtime.app._on_focus(WindowFocus("editor", "", ""))
    flush_paint(runtime.app)
    assert runtime.app._current.name == "editor"
    assert runtime.app._page == 0
    assert set(runtime.handle.paint_grid.call_args.args[0].values()) == {""}


def test_native_navigation_runs_once_on_press_and_never_paints_nav_keys(runtime):
    handle = runtime.device.KeypadHandle()
    handle.on_press(runtime.app._on_button)
    runtime.handle.reset_mock()
    handle._on_native_event(runtime.sdk.ButtonEvent(runtime.buttons.P2_RIGHT))
    handle._on_native_event(runtime.sdk.ButtonEvent(runtime.buttons.P2_RIGHT, pressed=False))
    assert runtime.app._page == 1
    runtime.handle.paint_grid.assert_not_called()
    assert runtime.app._paint_requested.is_set()
    flush_paint(runtime.app)
    runtime.handle.paint_grid.assert_called_once()
    assert handle.paint(runtime.buttons.P1_LEFT, b"jpeg") is False
    assert handle.paint(runtime.buttons.P2_RIGHT, b"jpeg") is False


@pytest.fixture
def editor():
    app = LogimapApp.__new__(LogimapApp)
    profile = paged_profile()
    app.config = Config(profiles={"default": profile})
    app.current_profile_name = "default"
    app.current_page = 0
    app.grid = Mock()
    app.grid.selected.return_value = "GRID_0"
    app.grid.select.side_effect = app._on_key_select
    app.title_var = Mock()
    app.shortcut_widget = Mock()
    app.selected_key_label = Mock()
    app.page_label = Mock()
    app.delete_page_button = Mock()
    app._set_key_enabled = Mock()
    app._set_status = Mock()
    # Simulate the real title trace: loading a different page must not write
    # the previous page's fields into its bindings.
    app.title_var.set.side_effect = lambda _: app._title_changed()
    return app


def test_editor_navigation_loads_bindings_and_edits_only_current_page(editor):
    editor._change_page(1)
    editor.title_var.set.assert_called_with("Second")
    editor.shortcut_widget.set.assert_called_with("s+w+mouse_right")
    editor.title_var.get.return_value = "Changed"
    editor._title_changed()
    editor._shortcut_changed("ctrl+v")
    assert editor._current().get("GRID_0", 1) == KeyBinding("Changed", "ctrl+v")
    assert editor._current().get("GRID_0", 0) == KeyBinding("First", "ctrl+a")
    editor._clear_key()
    assert editor._current().page_keys(1) == {}
    editor._change_page(-1)
    editor._change_page(-1)
    assert editor.current_page == 2


def test_editor_add_delete_and_last_page_guard(editor, monkeypatch):
    monkeypatch.setattr("logimap.gui.app.messagebox.askyesno", Mock(return_value=True))
    editor._add_page()
    assert editor.current_page == 3
    assert editor._current().page_keys(3) == {}
    editor._delete_page()
    assert editor.current_page == 2
    editor._delete_page()
    editor._delete_page()
    assert editor.current_page == 0
    editor._delete_page()
    assert editor._current().page_count == 1
    assert editor._current().get("GRID_0").title == "First"


def test_device_preview_uses_editor_page(editor, runtime):
    editor._handle = runtime.handle
    editor.current_page = 1
    editor._push_to_device()
    assert runtime.handle.paint_grid.call_args.args[0][runtime.buttons.GRID_0] == "Second"
