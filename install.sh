#!/usr/bin/env bash
# logimap installer.
#
# Run from a `git clone --recursive` of logimap. Builds the C++ core, the
# pybind11 SDK, sets up an isolated venv, drops udev rules, installs a
# launcher and desktop entry. Idempotent — safe to re-run.
#
# Usage:  ./install.sh [--force] [--downgrade]
#
# --force      skip the KDE Plasma 6 Wayland environment check, AND
#              reinstall even if the source tree matches the installed
#              version, AND allow downgrades.
# --downgrade  allow installing an older version over a newer one
#              (without also bypassing the env check).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGIMAP_ROOT="$SCRIPT_DIR"
INSTALL_PREFIX="${HOME}/.local"
VENV_DIR="${HOME}/.local/share/logimap/venv"
LAUNCHER="${INSTALL_PREFIX}/bin/logimap"
DESKTOP_FILE="${INSTALL_PREFIX}/share/applications/logimap.desktop"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
FORCE=0
DOWNGRADE=0
for arg in "$@"; do
    case "$arg" in
        --force)     FORCE=1 ;;
        --downgrade) DOWNGRADE=1 ;;
        -h|--help)
            sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) printf '\033[1;31mERROR:\033[0m unknown flag: %s\n' "$arg" >&2; exit 1 ;;
    esac
done

# ---- helpers --------------------------------------------------------------

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

source_version() {
    grep -E '^version[[:space:]]*=' "$LOGIMAP_ROOT/pyproject.toml" \
        | head -1 | sed -E 's/.*"([^"]+)".*/\1/'
}
installed_version() {
    [ -x "$LAUNCHER" ] || return 0
    "$LAUNCHER" --version 2>/dev/null | tr -d '[:space:]'
}
# echoes "eq" | "lt" | "gt"  ($1 vs $2)
version_compare() {
    [ "$1" = "$2" ] && { echo eq; return; }
    local first
    first=$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)
    [ "$first" = "$1" ] && echo lt || echo gt
}

# ---- 1. environment probe ------------------------------------------------

[ "$(uname -s)" = "Linux" ] || die "logimap is Linux-only"

if [ "${XDG_SESSION_TYPE:-}" != "wayland" ] || [[ "${XDG_CURRENT_DESKTOP:-}" != *KDE* ]]; then
    warn "Not a KDE Plasma 6 Wayland session (XDG_SESSION_TYPE='${XDG_SESSION_TYPE:-}', XDG_CURRENT_DESKTOP='${XDG_CURRENT_DESKTOP:-}')."
    warn "logimap will install but the focus daemon won't work outside KDE."
    if [ "$FORCE" != "1" ]; then
        die "Pass --force to install anyway."
    fi
fi

# ---- 1.5 version gate ----------------------------------------------------

SRC_VER=$(source_version)
[ -n "$SRC_VER" ] || die "Cannot read version from pyproject.toml"
INST_VER=$(installed_version)
SKIP_BUILD=0
if [ -z "$INST_VER" ]; then
    log "Installing logimap $SRC_VER"
elif [ "$INST_VER" = "$SRC_VER" ]; then
    if [ "$FORCE" = "1" ]; then
        log "Reinstalling logimap $SRC_VER (--force)"
    else
        log "logimap $SRC_VER is already installed — skipping rebuild"
        SKIP_BUILD=1
    fi
else
    case $(version_compare "$INST_VER" "$SRC_VER") in
        lt) log "Updating logimap $INST_VER → $SRC_VER" ;;
        gt) if [ "$FORCE" != "1" ] && [ "$DOWNGRADE" != "1" ]; then
                die "Source ($SRC_VER) older than installed ($INST_VER); pass --downgrade."
            fi
            log "Downgrading logimap $INST_VER → $SRC_VER" ;;
    esac
fi

# ---- 2. distro detection -------------------------------------------------

[ -f /etc/os-release ] || die "Cannot detect distro: /etc/os-release missing"
# shellcheck disable=SC1091
. /etc/os-release

DISTRO=""
case "${ID:-}:${ID_LIKE:-}" in
    fedora:*|*:*fedora*|*:*rhel*|rhel:*|centos:*) DISTRO=fedora ;;
    debian:*|ubuntu:*|*:*debian*|*:*ubuntu*)      DISTRO=debian ;;
    arch:*|manjaro:*|*:*arch*)                    DISTRO=arch ;;
    *) die "Unsupported distro '${ID:-unknown}'. Patches welcome at https://github.com/abishekmuthian/logimap/issues" ;;
esac
log "Detected distro: $DISTRO"

# ---- 3. install distro deps ----------------------------------------------

log "Installing system packages (sudo password may be required)"
case "$DISTRO" in
    fedora)
        sudo dnf install -y \
            cmake gcc-c++ git acl \
            python3-devel python3-tkinter python3-pillow-tk \
            pybind11-devel
        ;;
    debian)
        sudo apt-get update
        sudo apt-get install -y \
            cmake g++ git acl \
            python3-dev python3-venv python3-tk python3-pil.imagetk \
            python3-pybind11
        ;;
    arch)
        sudo pacman -S --needed --noconfirm \
            cmake gcc git acl \
            python tk python-pillow pybind11
        ;;
esac

# ---- 4. submodules -------------------------------------------------------

if [ -d "$LOGIMAP_ROOT/.git" ]; then
    log "Initializing git submodules"
    # Non-recursive: logilinux-sdk's nested 'logilinux-driver' submodule is
    # replaced with a symlink to ../logilinux in section 6, and git refuses
    # to recurse into a submodule whose path is already a symlink — so on
    # re-installs `--recursive` fails with
    #   "expected submodule path 'logilinux-driver' not to be a symbolic link".
    git -C "$LOGIMAP_ROOT" submodule update --init
else
    warn "Not a git checkout — skipping submodule init"
    [ -d "$LOGIMAP_ROOT/logilinux" ]      || die "logilinux/ missing. Clone with --recursive or place it manually."
    [ -d "$LOGIMAP_ROOT/logilinux-sdk" ]  || die "logilinux-sdk/ missing. Clone with --recursive or place it manually."
fi

# ---- 5. build C++ core ---------------------------------------------------

if [ "$SKIP_BUILD" != "1" ]; then
    # Drop stale pybind11 .so so pick_python picks the current Python, not
    # whichever tag a previous build happened to leave on disk.
    rm -f "$LOGIMAP_ROOT/logilinux-sdk"/_logilinux_native.cpython-*.so
    log "Building logilinux C++ core"
    cmake -S "$LOGIMAP_ROOT/logilinux" -B "$LOGIMAP_ROOT/logilinux/build" >/dev/null
    cmake --build "$LOGIMAP_ROOT/logilinux/build" -j
fi

# ---- 6. fix SDK driver stub ----------------------------------------------

SDK_DRIVER="$LOGIMAP_ROOT/logilinux-sdk/logilinux-driver"
if [ ! -L "$SDK_DRIVER" ]; then
    log "Replacing logilinux-sdk/logilinux-driver stub with symlink → ../logilinux"
    rm -rf "$SDK_DRIVER"
    ln -s "../logilinux" "$SDK_DRIVER"
fi

# ---- 7. venv + python deps -----------------------------------------------

if [ "$SKIP_BUILD" != "1" ]; then

# Pick a Python whose minor version matches a previously-built SDK .so
# (mirrors the auto-detection in scripts/run.sh).
pick_python() {
    local sdk_so tag ver
    sdk_so=$(ls "$LOGIMAP_ROOT/logilinux-sdk"/_logilinux_native.cpython-*.so 2>/dev/null | head -1)
    if [ -n "$sdk_so" ]; then
        tag=$(basename "$sdk_so" | sed -n 's/.*cpython-\([0-9]\+\)-.*/\1/p')
        ver="${tag:0:1}.${tag:1}"
        if command -v "python${ver}" >/dev/null 2>&1; then
            echo "python${ver}"
            return
        fi
    fi
    # No prior build — use the highest Python the system has, in this order.
    for v in 3.14 3.13 3.12 3.11 3.10; do
        if command -v "python${v}" >/dev/null 2>&1; then
            echo "python${v}"
            return
        fi
    done
    echo python3
}
PYTHON=$(pick_python)
log "Using Python: $PYTHON ($("$PYTHON" --version 2>&1))"

mkdir -p "$(dirname "$VENV_DIR")"
if [ ! -d "$VENV_DIR" ]; then
    log "Creating venv at $VENV_DIR"
    "$PYTHON" -m venv --system-site-packages "$VENV_DIR"
fi
VPY="$VENV_DIR/bin/python"

log "Upgrading pip + installing pybind11 in venv"
"$VPY" -m pip install --quiet --upgrade pip wheel
"$VPY" -m pip install --quiet pybind11

log "Building & installing logilinux-sdk (editable)"
"$VPY" -m pip install --quiet -e "$LOGIMAP_ROOT/logilinux-sdk"

log "Installing logimap (editable)"
"$VPY" -m pip install --quiet -e "$LOGIMAP_ROOT"

fi  # end SKIP_BUILD guard for section 7

# ---- 8. udev rules -------------------------------------------------------

log "Installing udev rules"
sudo install -m 644 \
    "$LOGIMAP_ROOT/packaging/99-logitech-creator.rules" \
    /etc/udev/rules.d/99-logitech-creator.rules
sudo install -m 644 \
    "$LOGIMAP_ROOT/packaging/99-logimap-uinput.rules" \
    /etc/udev/rules.d/99-logimap-uinput.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=hidraw 2>/dev/null || true
sudo udevadm trigger --name-match=uinput      2>/dev/null || true

# ---- 9. input group ------------------------------------------------------

NEED_RELOGIN=0
if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    log "User '$USER' is already in 'input' group"
else
    log "Adding '$USER' to 'input' group (required for /dev/uinput rw)"
    sudo usermod -aG input "$USER"
    NEED_RELOGIN=1
    # Bridge access for the current session via ACL so the user can test
    # without re-logging in. ACL is non-persistent (tmpfs) but that's fine —
    # group membership takes over after re-login.
    if command -v setfacl >/dev/null 2>&1; then
        sudo setfacl -m "u:${USER}:rw" /dev/uinput 2>/dev/null || true
    fi
fi

# ---- 10. launcher --------------------------------------------------------

if [ "$SKIP_BUILD" != "1" ]; then
    log "Installing launcher at $LAUNCHER"
    mkdir -p "$(dirname "$LAUNCHER")"
    cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Auto-generated by logimap install.sh — regenerate with ./install.sh
LOGIMAP_ROOT="$LOGIMAP_ROOT"
export LD_LIBRARY_PATH="\$LOGIMAP_ROOT/logilinux/build/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "$VENV_DIR/bin/python" -m logimap "\$@"
EOF
    chmod +x "$LAUNCHER"
fi

if ! echo ":$PATH:" | grep -q ":$INSTALL_PREFIX/bin:"; then
    warn "$INSTALL_PREFIX/bin is not on your \$PATH."
    warn "Add it to your shell rc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ---- 11. desktop file ----------------------------------------------------

log "Installing desktop entry"
mkdir -p "$(dirname "$DESKTOP_FILE")"
install -m 644 "$LOGIMAP_ROOT/packaging/logimap.desktop" "$DESKTOP_FILE"
update-desktop-database "$(dirname "$DESKTOP_FILE")" >/dev/null 2>&1 || true

# ---- 12. systemd unit (install only, do not enable) ----------------------

log "Installing systemd --user unit (not enabled)"
mkdir -p "$SYSTEMD_USER_DIR"
install -m 644 \
    "$LOGIMAP_ROOT/packaging/logimap.service" \
    "$SYSTEMD_USER_DIR/logimap.service"
systemctl --user daemon-reload >/dev/null 2>&1 || true

# ---- 13. restart running daemon ------------------------------------------

if systemctl --user is-active --quiet logimap.service 2>/dev/null; then
    log "Restarting active logimap.service"
    systemctl --user try-restart logimap.service || warn "try-restart failed"
fi
if pgrep -u "$USER" -f 'python.*-m logimap run' >/dev/null 2>&1; then
    warn "Foreground 'logimap run' detected — restart it manually to pick up $SRC_VER"
fi

# ---- done ----------------------------------------------------------------

log "logimap $SRC_VER installed successfully"
echo
if [ "$NEED_RELOGIN" = "1" ]; then
    cat <<'EOF'
  ⚠  You were added to the 'input' group. Log out and back in for the
     change to persist across reboots. (For this boot the script granted
     a temporary ACL on /dev/uinput so you can try it now.)

EOF
fi
cat <<EOF
Next steps:
  logimap install-kwin       # one-time per Plasma session
  logimap gui                # author profiles
  logimap run                # run the daemon in this terminal

To auto-start the daemon when you log into Plasma:
  systemctl --user enable --now logimap

Logs:    ~/.local/state/logimap/logimap.log
Config:  ~/.config/logimap/profiles.json
Uninstall:  ./uninstall.sh
EOF
