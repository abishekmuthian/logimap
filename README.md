# logimap

![logimap Version 0.2.5](https://badgen.net/static/Version/0.2.5/cyan)

**Per-application profile manager for the Logitech MX Creative Keypad on Linux.**

Switch what the keypad's 9 LCD keys display and which keyboard shortcuts
or mouse-button macros they fire, automatically, based on the application
currently focused on your desktop. Author profiles in a small Tk editor;
a background daemon handles the rest.

https://github.com/user-attachments/assets/5b78fd41-d095-4912-a823-83a7df15d3c8

**Disclaimer:** This is not an official Logitech™ application. This project is not affiliated with, endorsed by, or sponsored by Logitech.

## Features

- **Application profiles:** automatically switch LCD labels and bindings
  when the focused application changes.
- **[Mouse support and game macros](#mouse-buttons-and-game-macros):** click
  any of five mouse buttons, combine them with keys, or run a sequence
  such as `s,w,mouse_right` with one keypad press.
- **[Timing support](#holds-and-pauses):** set holds with `@milliseconds`
  and pauses with `wait:milliseconds`, for example
  `mouse_right@500,wait:300,mouse_left`.
- **[Pagination](#multiple-pages):** create multiple pages of nine bindings
  per profile and browse them with the keypad's left/right buttons.
- **[Key rearrangement](#rearranging-keys):** drag bindings around the editor
  grid to move or swap their titles and shortcuts together.
- **[Key icons](#key-icons):** show an image (PNG, JPEG, SVG, ...) or any
  installed theme icon such as `firefox` or `media-playback-start` on a key,
  with or without a title underneath.
- **Live editing:** save to hot-reload the daemon, preview a page's labels
  on the device, and duplicate profiles with all their pages.

## Status / Scope

| Need                      | Supported                                  |
|---------------------------|--------------------------------------------|
| Hardware                  | Logitech MX Creative Keypad (USB `046d:c354`) |
| OS                        | Linux (kernel ≥ 5.10 for uinput)           |
| Desktop                   | KDE Plasma 6 on **Wayland**                |
| Keyboard / mouse injection | Built-in `/dev/uinput` (no third-party daemon) |

**Requires KDE Plasma** as KWin script is being used and the MX Dialpad aren't shipped yet; the focus-source
abstraction in `logimap/focus/` is designed for them, contributions welcome.

## Quick start

```bash
git clone --recursive https://github.com/abishekmuthian/logimap
cd logimap
./install.sh
logimap install-kwin   # one-time per Plasma session
logimap gui            # author your first profile
logimap run            # start the daemon
```

If you're adding yourself to the `input` group for the first time you'll
need to log out and back in once before the daemon can write `/dev/uinput`
across reboots. `install.sh` will tell you.

## What `install.sh` does

It's a plain bash script, so read it before running. In order, it:

1. Refuses to proceed unless you're on Linux + KDE Plasma 6 Wayland (pass
   `--force` to override).
2. Detects your distro (Fedora, Debian/Ubuntu, or Arch) and installs the
   build deps (`cmake`, `g++`, `python3-tkinter`, `python3-pillow-tk`,
   `pybind11`, `git`, `acl`) plus `rsvg-convert` (librsvg) for SVG key icons.
3. `git submodule update --init`, which pulls `logilinux/` and `logilinux-sdk/`
   from the upstream `github.com/logilinux/` org.
4. Builds the C++ core (`logilinux/`) with CMake.
5. Symlinks the SDK's empty `logilinux-driver` stub to `../logilinux` so
   the pybind11 build resolves headers.
6. Creates `~/.local/share/logimap/venv` and pip-installs `pybind11`,
   `logilinux-sdk` (editable), and `logimap` (editable) into it. The venv
   uses `--system-site-packages` so it inherits Tk + Pillow-tk from the
   distro.
7. Drops two udev rules into `/etc/udev/rules.d/`:
   - `99-logitech-creator.rules`: `MODE=0666` for HID PIDs `046d:bc00`
     (Dialpad, reserved) and `046d:c354` (MX Creative Keypad).
   - `99-logimap-uinput.rules`: `GROUP=input MODE=0660` for `/dev/uinput`.
8. Adds your user to the `input` group if you're not already a member,
   plus a temporary ACL bridge for the current boot.
9. Drops a launcher at `~/.local/bin/logimap` and a `.desktop` entry
   under `~/.local/share/applications/`.
10. Drops a `systemd --user` unit at `~/.config/systemd/user/logimap.service`
    (installed but **not** enabled; you opt in).

You'll be prompted for `sudo` at the udev / `usermod` steps.

## Authoring your first profile

1. `logimap gui` opens the Tk editor maximized. Key previews grow with the
   window for readable labels. Click **Fullscreen (F11)** or press **F11**
   to toggle fullscreen; **Esc** returns to the window.
2. Click **Add**, pick a profile name.
3. In the **Match** section, set `wm_class` to the focused window class
   reported by KWin. The easy way to discover this: with `logimap run`
   active, alt-tab to the app you care about and tail the log:

   ```bash
   tail -F ~/.local/state/logimap/logimap.log | grep 'focus ->'
   ```

   You'll see lines like `wm_class='org.mozilla.firefox'`;
   copy that string verbatim. Plasma 6 uses reverse-DNS, so it's
   `org.mozilla.firefox`, not `firefox`.
4. Click a key in the 3×3 grid (e.g. `GRID_0`).
5. Type a **Title** (what the LCD will show) and assign a shortcut.

    - **Capture**: click the button, press the chord (e.g. `Ctrl+T`),
      or click a mouse button inside the Shortcut field.
      Works for app-level shortcuts the compositor doesn't intercept.
      Capture records one key or mouse button plus modifiers. Type
      sequences, simultaneous non-modifier keys, and timing directly.
    - **Type directly into the Shortcut field**: required for chords
      KWin grabs globally before they reach the editor (e.g. `Meta+L`
      for lock screen, `Meta+D` for show desktop). Use the canonical
      `+`-joined form: `logo+l`, `ctrl+shift+t`, `alt+f4`. Modifier
      names: `ctrl`, `shift`, `alt`, `logo` (also accepts `meta` /
      `super` / `control`). The daemon synthesizes these via uinput,
      and KWin's global-shortcut handler honors them on Plasma 6.
    - **Multi-chord shortcuts** (tmux, screen, etc.): separate chords
      with a comma. For example, tmux's vertical split (`Ctrl+B` then
      `"`) is entered as `ctrl+b,"` (the `"` auto-expands to
      `shift+'`). The daemon injects each chord with a 50 ms pause
      between them so the receiving application can distinguish the
      prefix from the action. Other examples:
      - `ctrl+b,%` — tmux horizontal split
      - `ctrl+b,o` — tmux switch pane
      - `ctrl+b,x` — tmux close pane

6. **Save**. The daemon hot-reloads the config file (mtime watcher;
    `SIGHUP` also works).

### Mouse buttons and game macros

Select a grid key, give it a title, and type a macro into the **Shortcut**
field. Click **Save**, focus the target application, and press that keypad
key to run it once. Mouse clicks use the current cursor position.

| Button | Shortcut | Alias |
|---|---|---|
| Left | `mouse_left` | `mouse1` |
| Right | `mouse_right` | `mouse2` |
| Middle | `mouse_middle` | `mouse3` |
| Back / side | `mouse_back` | `mouse4` |
| Forward / extra | `mouse_forward` | `mouse5` |

Use commas for sequential actions and `+` for simultaneous inputs:

| Shortcut | Action |
|---|---|
| `s,w,mouse_right` | Press and release S, then W, then right-click (the Sweep macro in the screenshot) |
| `s+w+mouse_right` | Hold S and W during a right-click, then release everything in reverse order |
| `ctrl+mouse_right` | Right-click while holding Ctrl |
| `1,mouse_left,2` | Press 1, left-click, then press 2 |
| `mouse_left,mouse_left` | Click left twice |

In macros containing mouse buttons or multiple simultaneous non-modifier
keys, every chord defaults to a 50 ms hold with a 50 ms gap between chords.
Ordinary keyboard-only shortcuts retain their existing timing: no hold and
a 50 ms gap between chords. Use explicit timing below to change these defaults.

Mouse macros and simultaneous non-modifier keys require the built-in
**uinput** injector. The `wtype`, `ydotool`, and `xdotool` fallbacks reject
these macros before sending any part of the sequence. Holding until keypad
release, auto-repeat, cursor movement, and wheel scrolling are not supported.

### Holds and pauses

Type `@milliseconds` after a chord to set its hold duration, or add a
`wait:milliseconds` step to pause with every input released. Enter timing
directly in the **Shortcut** field, then click **Save**.

| Shortcut | Action |
|---|---|
| `mouse_right@500` | Hold right mouse for 500 ms, then release |
| `space+mouse_right@500` | Hold Space and right mouse together for 500 ms |
| `mouse_right,wait:300,mouse_right` | Click, pause 300 ms, click |
| `w@200,wait:100,mouse_left` | Hold W for 200 ms, release, pause 100 ms, click |

Durations are whole milliseconds from 0 to 60000. An explicit hold overrides
the default for that chord only. An explicit wait replaces the usual 50 ms
gap between its neighboring chords; consecutive waits add together, and
waits may start or end a macro. `wait:0` removes the gap and `@0` releases a
chord immediately. Unspecified timing retains the defaults described above.

The `@` key still works as a literal symbol (`ctrl+@`); use `@@500` to hold
that symbol for 500 ms. Timing requires the built-in **uinput** injector;
the other backends reject timed macros before sending any inputs.

### Multiple pages

1. Select a profile and click **Add page** below the grid. The editor opens
   the new blank page, with nine more slots for bindings.
2. Edit its keys and click **Save**. Use **Previous** and **Next** to browse
   pages; the counter shows the selected page and total.
3. Click **Preview on device** to display the editor's selected page on the
   keypad LCDs. Preview updates labels; **Save** applies binding changes to
   the daemon, which uses the focused application's profile and its own
   selected page.
4. To remove a page and its bindings, select it, click **Delete page**,
   confirm, and **Save**. At least one page is always retained.

On the keypad, **P1 / left** selects the previous page and **P2 / right**
selects the next. Navigation wraps at either end; a single-page profile
stays on page 1. These two buttons are reserved for navigation and never
fire shortcuts. The daemon remembers each profile's selected page across
application switches and config reloads; restarting resets selections to
page 1. Selecting a profile in the editor starts at page 1. **Duplicate**
copies all of a profile's pages, bindings, colors, and matching rules.

### Rearranging keys

1. Open the profile and page you want to rearrange.
2. Drag a key in the preview grid onto another slot. Dropping onto an
   occupied slot swaps both bindings; dropping onto an empty slot moves
   the binding. Titles and complete shortcuts, including timing, move together.
3. Click **Save** to apply the layout to the daemon. Rearrangement affects
   only the current page.

Press **Esc** or drop outside the grid to cancel a drag. Switching pages
also cancels an active drag.

### Key icons

1. Select a key and fill in **Icon** with either:
    - **an image file**: click **Browse…** or type a path. PNG, JPEG, SVG,
      WebP, GIF, and XPM work. `~` is expanded, and relative paths are
      relative to your home directory.
    - **an icon name** from your installed icon themes, e.g. `firefox`,
      `org.kde.dolphin`, `utilities-terminal`, `media-playback-start`,
      `audio-volume-muted`. Short names find reverse-DNS app icons too, so
      `spotify` finds Flatpak's `com.spotify.Client`. Browse names with
      KDE's **Icon Explorer** (`cuttlefish`, in the `plasma-sdk` package), or look in
      `/usr/share/icons/breeze/`.
2. With a **Title**, the icon is drawn with the title as a small label
   underneath (up to two lines); leave the title empty for a large icon on
   its own.
3. The editor grid previews the result immediately. **Save** to apply it to
   the daemon.

Icon names are looked up in Breeze, hicolor (including Flatpak app icons),
Adwaita, and Oxygen. Monochrome Breeze icons use the variant that
contrasts with the profile's `bg_color` (Breeze Dark on dark keys). Inside
a distrobox/toolbox, the host's themes are searched as well. If an icon
can't be found or decoded, the key falls back to its text title and the
log shows `icon not found`.

Saving the config also rescans icon themes, so icons from newly installed
apps work without restarting the daemon.

SVGs are rasterized with `rsvg-convert` (installed by `install.sh`). If it's
missing, logimap falls back to the `cairosvg` Python package, which you can
add to logimap's venv with
`~/.local/share/logimap/venv/bin/pip install cairosvg`.

### After updating Logimap

Restart a running daemon to load mouse, timing, pagination, and icon support:

```bash
systemctl --user restart logimap
```

If you run `logimap run` manually, stop it and start it again. Reopen the
editor to load its new controls. Existing profiles remain compatible;
config-only edits still hot-reload when saved.

## Profile JSON

`~/.config/logimap/profiles.json`:

```json
{
  "version": 1,
  "default_profile": "default",
  "profiles": {
    "firefox": {
      "match": {"wm_class": "org.mozilla.firefox", "title_regex": null},
      "bg_color": [30, 30, 30],
      "fg_color": [255, 255, 255],
      "keys": {
        "GRID_0": {"title": "New Tab",    "shortcut": "ctrl+t", "icon": "tab-new"},
        "GRID_1": {"title": "Close Tab",  "shortcut": "ctrl+w"},
        "GRID_2": {"title": "Reopen Tab", "shortcut": "ctrl+shift+t"},
        "GRID_3": {"title": "Split V",    "shortcut": "ctrl+b,\""},
        "GRID_4": {"title": "Split H",    "shortcut": "ctrl+b,%"}
      },
      "extra_pages": [
        {
          "GRID_0": {"title": "Find", "shortcut": "ctrl+f"},
          "GRID_1": {"title": "Reload", "shortcut": "ctrl+r"}
        }
      ]
    },
    "default": {
      "match": {"wm_class": "*", "title_regex": null},
      "keys": {}
    }
  }
}
```

Layout:

```
GRID_0 GRID_1 GRID_2
GRID_3 GRID_4 GRID_5
GRID_6 GRID_7 GRID_8
```

Profile selection: first profile whose `wm_class` matches (with
`title_regex` checked if set), otherwise `default_profile`.

`keys` contains page 1; the optional `extra_pages` array contains page 2,
page 3, and so on, each with the same `GRID_0`–`GRID_8` binding format.
Existing version 1 configs remain valid without changes. Empty pages are
preserved, and each page shares its profile's colors and matching rules.
Mouse macros and timing are stored in the existing `shortcut` string.
The optional `icon` is an image path or a theme icon name (see
[Key icons](#key-icons)); bindings without one are saved without the field.
Rearranging keys changes their `GRID_0`–`GRID_8` assignments within that page.

## Auto-start at login

```bash
systemctl --user enable --now logimap
journalctl --user -u logimap -f         # follow the daemon's logs
```

## Architecture

```
KWin JS ──D-Bus──▶ daemon ──JPEG bytes──▶ MX Keypad
                     ▲                          │
                     └──── ButtonEvent ─────────┘
                     │
                     └──── /dev/uinput EV_KEY ──▶ focused app
```

- `logimap/focus/kwin_dbus.py` owns `org.logimap.Focus1` on the session bus.
  `kwin_script/logimap-focus.js` subscribes to `workspace.windowActivated`
  and pings us via `callDBus`.
- `logimap/device.py` wraps `logilinux.MXKeypadDevice` with auto-reconnect.
- `logimap/inject/uinput.py` opens `/dev/uinput`, registers a virtual
  keyboard and mouse, writes `EV_KEY` events for the chord. `wtype`/`ydotool`/`xdotool`
  are auto-probed fallbacks (rarely needed on KWin 6; see
  [Troubleshooting](#troubleshooting)).
- `logimap/render.py` produces a 118×118 JPEG from a title string to fill the
  LCD region programmed by `MXKeypadDevice.set_key_image()`.

## Troubleshooting

Logs are in `~/.local/state/logimap/logimap.log` (rotating, 1 MB × 3
backups). Pass `-v` for DEBUG.

```bash
tail -F ~/.local/state/logimap/logimap.log

# Verify D-Bus owner is the live daemon:
busctl --user status org.logimap.Focus1
```

| Symptom | First thing to check |
|---|---|
| LCDs don't change on alt-tab | `grep 'focus ->' ~/.local/state/logimap/logimap.log`; if empty, the KWin script isn't reaching the daemon. Run `logimap install-kwin`. |
| Key press does nothing | Look for `press GRID_N has no binding in profile '…'`. The resolved profile name shows whether your `wm_class` matched. Profile must use the reverse-DNS class (e.g. `org.mozilla.firefox`). |
| Capture button doesn't react to `Meta+L`, `Meta+D`, etc. | KWin grabs those globally before the editor sees them. Type the canonical form (e.g. `logo+l`) directly into the Shortcut field instead. |
| Mouse, multi-key, or timed macro is rejected | Check the startup log for `using built-in uinput injector`. These macros require uinput; grant access as described below and restart the daemon after updating. |
| Rearranged keys or added pages aren't active | Click **Save** to apply editor changes. Preview only displays labels; focus the target application and select the intended page with the keypad's left/right buttons. |
| `No usable keystroke injector found` | Your user can't open `/dev/uinput`. Re-login after `install.sh` (the `input` group needs a fresh session) or `sudo setfacl -m u:$USER:rw /dev/uinput` for a one-shot. |
| `wtype failed for ... exit 1` | KWin 6 hides `zwp_virtual_keyboard_v1` from non-IME clients. The probe should have skipped wtype and selected uinput; check the startup log line `using built-in uinput injector`. |
| `MX Keypad not found` | `lsusb \| grep 046d:c354` should show the device. If `/dev/hidraw*` is `crw-rw----` instead of `crw-rw-rw-`, the udev rule didn't apply; try `sudo udevadm trigger --subsystem-match=hidraw` and replug. |
| Key shows its title instead of the icon | Look for `icon not found` or `cannot rasterize SVG` in the log. Check the path or icon name (theme names have no extension), and for SVGs make sure `rsvg-convert` is installed (`librsvg2-tools` on Fedora, `librsvg2-bin` on Debian/Ubuntu, `librsvg` on Arch). |
| `RequestNameReply.IN_QUEUE` in startup log | A second daemon is fighting for the D-Bus name. `pkill -f "logimap run"` and restart. |
| `ModuleNotFoundError: _logilinux_native` | The SDK was built against a different Python version than the one running the daemon. Re-run `./install.sh`; it picks an interpreter that matches the compiled `.so`. |
| systemd unit fails to start | `journalctl --user -u logimap -n 50` and inspect. Most often: not in `input` group yet (re-login), or `~/.local/bin` not on the systemd user `PATH`. |

## Development

```bash
pip install -e ".[dev]"          # installs pytest (declared under [project.optional-dependencies].dev)
PYTHONPATH=. python3 -m pytest tests/ -q
```

The test suite covers the shortcut parser, config round-trip, profile
resolver, mouse macros, holds and pauses, pagination, key rearrangement,
JPEG rendering, and uinput event routing and cleanup. Automated tests use
fake devices and editor callbacks without a physical keypad or Wayland
session.

Contributions: open a PR against
[github.com/abishekmuthian/logimap](https://github.com/abishekmuthian/logimap).

## License

logimap is GPL-3.0-licensed. See [`LICENSE`](LICENSE).

## Credits

Built on top of the [LogiLinux](https://github.com/logilinux) project:

- [`logilinux`](https://github.com/logilinux/logilinux): C++ core library and hardware abstraction
- [`logilinux-sdk`](https://github.com/logilinux/logilinux-sdk): pybind11 Python bindings

The core `logilinux` and `logilinux-sdk` repos are pulled in as git submodules.
