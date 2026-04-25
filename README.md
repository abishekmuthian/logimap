# logimap

**Per-application profile manager for the Logitech MX Creative Keypad on Linux.**

Switch what the keypad's 9 LCD keys display — and which keyboard shortcuts
they fire — automatically, based on the application currently focused on
your desktop. Author profiles in a small Tk editor; a background daemon
handles the rest.

<!-- TODO: insert docs/screenshots/gui.png and docs/screenshots/keypad.jpg -->

## Status / Scope

| Need                      | Supported                                  |
|---------------------------|--------------------------------------------|
| Hardware                  | Logitech MX Creative Keypad (USB `046d:c354`) |
| OS                        | Linux (kernel ≥ 5.10 for uinput)           |
| Desktop                   | KDE Plasma 6 on **Wayland**                |
| Keystroke injection       | Built-in `/dev/uinput` (no third-party daemon) |

GNOME, sway, X11, and the MX Dialpad aren't shipped yet — the focus-source
abstraction in `logimap/focus/` is designed for them, contributions
welcome.

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
across reboots — `install.sh` will tell you.

## What `install.sh` does

It's a plain bash script — read it before running. In order, it:

1. Refuses to proceed unless you're on Linux + KDE Plasma 6 Wayland (pass
   `--force` to override).
2. Detects your distro (Fedora, Debian/Ubuntu, or Arch) and installs the
   build deps (`cmake`, `g++`, `python3-tkinter`, `python3-pillow-tk`,
   `pybind11`, `git`, `acl`).
3. `git submodule update --init` — pulls `logilinux/` and `logilinux-sdk/`
   from the upstream `github.com/logilinux/` org.
4. Builds the C++ core (`logilinux/`) with CMake.
5. Symlinks the SDK's empty `logilinux-driver` stub to `../logilinux` so
   the pybind11 build resolves headers.
6. Creates `~/.local/share/logimap/venv` and pip-installs `pybind11`,
   `logilinux-sdk` (editable), and `logimap` (editable) into it. The venv
   uses `--system-site-packages` so it inherits Tk + Pillow-tk from the
   distro.
7. Drops two udev rules into `/etc/udev/rules.d/`:
   - `99-logitech-creator.rules` — `MODE=0666` for HID PIDs `046d:bc00`
     (Dialpad — reserved) and `046d:c354` (MX Creative Keypad).
   - `99-logimap-uinput.rules` — `GROUP=input MODE=0660` for `/dev/uinput`.
8. Adds your user to the `input` group if you're not already a member,
   plus a temporary ACL bridge for the current boot.
9. Drops a launcher at `~/.local/bin/logimap` and a `.desktop` entry
   under `~/.local/share/applications/`.
10. Drops a `systemd --user` unit at `~/.config/systemd/user/logimap.service`
    (installed but **not** enabled — you opt in).

You'll be prompted for `sudo` at the udev / `usermod` steps.

## Authoring your first profile

1. `logimap gui` — opens the Tk editor.
2. Click **Add**, pick a profile name.
3. In the **Match** section, set `wm_class` to the focused window class
   reported by KWin. The easy way to discover this: with `logimap run`
   active, alt-tab to the app you care about and tail the log:

   ```bash
   tail -F ~/.local/state/logimap/logimap.log | grep 'focus ->'
   ```

   You'll see lines like `wm_class='org.mozilla.firefox'` —
   copy that string verbatim. Plasma 6 uses reverse-DNS, so it's
   `org.mozilla.firefox`, not `firefox`.
4. Click a key in the 3×3 grid (e.g. `GRID_0`).
5. Type a **Title** (what the LCD will show) and click **Capture** —
   then press the keyboard chord you want to bind, e.g. `Ctrl+T`.
6. **Save**. The daemon hot-reloads the config file (mtime watcher;
   `SIGHUP` also works).

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
        "GRID_0": {"title": "New Tab",    "shortcut": "ctrl+t"},
        "GRID_1": {"title": "Close Tab",  "shortcut": "ctrl+w"},
        "GRID_2": {"title": "Reopen Tab", "shortcut": "ctrl+shift+t"}
      }
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
  keyboard, writes `EV_KEY` events for the chord. `wtype`/`ydotool`/`xdotool`
  are auto-probed fallbacks (rarely needed on KWin 6 — see
  [Troubleshooting](#troubleshooting)).
- `logimap/render.py` produces a 90×90 JPEG from a title string — the only
  format `MXKeypadDevice.set_key_image()` accepts.

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
| LCDs don't change on alt-tab | `grep 'focus ->' ~/.local/state/logimap/logimap.log` — if empty, the KWin script isn't reaching the daemon. Run `logimap install-kwin`. |
| Key press does nothing | Look for `press GRID_N has no binding in profile '…'` — the resolved profile name shows whether your `wm_class` matched. Profile must use the reverse-DNS class (e.g. `org.mozilla.firefox`). |
| `No usable keystroke injector found` | Your user can't open `/dev/uinput`. Re-login after `install.sh` (the `input` group needs a fresh session) or `sudo setfacl -m u:$USER:rw /dev/uinput` for a one-shot. |
| `wtype failed for ... exit 1` | KWin 6 hides `zwp_virtual_keyboard_v1` from non-IME clients. The probe should have skipped wtype and selected uinput; check the startup log line `using built-in uinput injector`. |
| `MX Keypad not found` | `lsusb \| grep 046d:c354` should show the device. If `/dev/hidraw*` is `crw-rw----` instead of `crw-rw-rw-`, the udev rule didn't apply — try `sudo udevadm trigger --subsystem-match=hidraw` and replug. |
| `RequestNameReply.IN_QUEUE` in startup log | A second daemon is fighting for the D-Bus name. `pkill -f "logimap run"` and restart. |
| `ModuleNotFoundError: _logilinux_native` | The SDK was built against a different Python version than the one running the daemon. Re-run `./install.sh` — it picks an interpreter that matches the compiled `.so`. |
| systemd unit fails to start | `journalctl --user -u logimap -n 50` and inspect. Most often: not in `input` group yet (re-login), or `~/.local/bin` not on the systemd user `PATH`. |

## Development

```bash
PYTHONPATH=. python3 -m pytest tests/ -q
```

The test suite covers the shortcut parser, config round-trip, profile
resolver, JPEG rendering, and the uinput event-sequence logic — everything
that doesn't need the physical keypad or a Wayland session.

Contributions: open a PR against
[github.com/abishekmuthian/logimap](https://github.com/abishekmuthian/logimap).

## License + credits

logimap is MIT-licensed. See [`LICENSE`](LICENSE).

Built on top of:

- [`logilinux`](https://github.com/logilinux/logilinux) — C++ core library
- [`logilinux-sdk`](https://github.com/logilinux/logilinux-sdk) — pybind11 Python bindings (MIT, © 2025 Ron0Studios)

Both pulled in as git submodules.
