#!/usr/bin/env bash
# Reverse what install.sh did, except for distro-installed packages and
# 'input' group membership (those changes affect the system at large; we
# print the manual command and leave it to you).
#
# Usage:  ./uninstall.sh

set -euo pipefail

INSTALL_PREFIX="${HOME}/.local"
VENV_DIR="${HOME}/.local/share/logimap/venv"
LAUNCHER="${INSTALL_PREFIX}/bin/logimap"
DESKTOP_FILE="${INSTALL_PREFIX}/share/applications/logimap.desktop"
SYSTEMD_UNIT="${HOME}/.config/systemd/user/logimap.service"

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }

# Stop the daemon if it's running.
log "Stopping any running logimap daemon"
systemctl --user disable --now logimap.service >/dev/null 2>&1 || true
pkill -f "logimap run" 2>/dev/null || true

# Remove user-scope artifacts.
log "Removing launcher and desktop entry"
rm -f "$LAUNCHER" "$DESKTOP_FILE" "$SYSTEMD_UNIT"
update-desktop-database "$(dirname "$DESKTOP_FILE")" >/dev/null 2>&1 || true
systemctl --user daemon-reload >/dev/null 2>&1 || true

if [ -d "$VENV_DIR" ]; then
    log "Removing venv at $VENV_DIR"
    rm -rf "$VENV_DIR"
fi

# Remove udev rules (system-scope; needs sudo).
if [ -f /etc/udev/rules.d/99-logimap-uinput.rules ] || \
   [ -f /etc/udev/rules.d/99-logitech-creator.rules ]; then
    log "Removing udev rules (sudo password may be required)"
    sudo rm -f \
        /etc/udev/rules.d/99-logimap-uinput.rules \
        /etc/udev/rules.d/99-logitech-creator.rules
    sudo udevadm control --reload || true
fi

cat <<EOF

logimap uninstalled.

What was NOT removed (do it manually if you want):
  • Distro packages installed by install.sh (cmake, python3-tkinter,
    pybind11-devel, etc.) — those are widely used by other tools.
  • Your membership in the 'input' group:
        sudo gpasswd -d "$USER" input
  • Your config and logs:
        rm -rf ~/.config/logimap ~/.local/state/logimap ~/.local/share/logimap
  • The KWin focus script — open System Settings → KWin Scripts and
    disable 'logimap-focus'.
EOF
