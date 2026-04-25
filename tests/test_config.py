import json
from pathlib import Path

from logimap.config import Config, SCHEMA_VERSION
from logimap.profiles import KeyBinding, Match, Profile, WindowFocus, resolve


def test_roundtrip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "profiles.json"
    cfg = Config(path=cfg_path, default_profile="default")
    cfg.profiles["default"] = Profile(name="default")
    cfg.profiles["firefox"] = Profile(
        name="firefox",
        match=Match(wm_class="firefox"),
        keys={"GRID_0": KeyBinding(title="New Tab", shortcut="ctrl+t")},
    )
    cfg.save()

    loaded = Config.load(cfg_path)
    assert "firefox" in loaded.profiles
    ff = loaded.profiles["firefox"]
    assert ff.keys["GRID_0"].shortcut == "ctrl+t"
    assert ff.match.wm_class == "firefox"

    data = json.loads(cfg_path.read_text())
    assert data["version"] == SCHEMA_VERSION


def test_resolve_exact_class() -> None:
    profiles = {
        "default": Profile(name="default"),
        "firefox": Profile(name="firefox", match=Match(wm_class="firefox")),
        "code": Profile(name="code", match=Match(wm_class="code")),
    }
    r = resolve(profiles, WindowFocus("firefox", "firefox", "Mozilla Firefox"), "default")
    assert r.name == "firefox"


def test_resolve_falls_back_to_default() -> None:
    profiles = {"default": Profile(name="default")}
    r = resolve(profiles, WindowFocus("unknown", "unknown", "whatever"), "default")
    assert r.name == "default"


def test_title_regex() -> None:
    profiles = {
        "default": Profile(name="default"),
        "code_py": Profile(
            name="code_py",
            match=Match(wm_class="code", title_regex=r"\.py"),
        ),
    }
    r = resolve(
        profiles,
        WindowFocus("code", "code", "daemon.py - Visual Studio Code"),
        "default",
    )
    assert r.name == "code_py"

    r2 = resolve(
        profiles,
        WindowFocus("code", "code", "index.ts - Visual Studio Code"),
        "default",
    )
    assert r2.name == "default"


def test_load_creates_empty_default(tmp_path: Path) -> None:
    cfg_path = tmp_path / "nope.json"
    cfg = Config.load(cfg_path)
    assert "default" in cfg.profiles
    assert cfg_path.exists()
