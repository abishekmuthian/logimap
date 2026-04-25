#!/usr/bin/env bash
# Run `python -m logimap ...` with the logilinux SDK and native library on-path.
#
# Usage: ./scripts/run.sh paint-test
#        ./scripts/run.sh run
#        ./scripts/run.sh gui

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGIMAP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOGILINUX_ROOT="$(cd "$LOGIMAP_ROOT/.." && pwd)"

SDK_DIR="$LOGILINUX_ROOT/logilinux-sdk"
CORE_BUILD="$LOGILINUX_ROOT/logilinux/build/lib"

export PYTHONPATH="$LOGIMAP_ROOT:$SDK_DIR:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$CORE_BUILD:${LD_LIBRARY_PATH:-}"

# Pick a Python whose ABI matches the SDK's native .so.
# logilinux-sdk/_logilinux_native.cpython-<ver>-*.so must match the chosen interpreter.
pick_python() {
    local sdk_so
    sdk_so=$(ls "$SDK_DIR"/_logilinux_native.cpython-*.so 2>/dev/null | head -1)
    if [ -z "$sdk_so" ]; then
        echo "python3"
        return
    fi
    # Extract "3XX" from cpython-3XX- and turn into 3.XX
    local tag ver
    tag=$(basename "$sdk_so" | sed -n 's/.*cpython-\([0-9]\+\)-.*/\1/p')
    ver="${tag:0:1}.${tag:1}"
    if command -v "python${ver}" >/dev/null 2>&1; then
        echo "python${ver}"
    elif [ -x "/usr/bin/python${ver}" ]; then
        echo "/usr/bin/python${ver}"
    else
        echo "python3"
    fi
}

if [ -f "$LOGIMAP_ROOT/venv/bin/python" ]; then
    PYTHON="$LOGIMAP_ROOT/venv/bin/python"
elif [ -f "$LOGILINUX_ROOT/venv/bin/python" ]; then
    PYTHON="$LOGILINUX_ROOT/venv/bin/python"
else
    PYTHON=$(pick_python)
fi

if [ "${LOGIMAP_DEBUG:-}" = "1" ]; then
    echo "[run.sh] PYTHON=$PYTHON" >&2
    echo "[run.sh] PYTHONPATH=$PYTHONPATH" >&2
    echo "[run.sh] LD_LIBRARY_PATH=$LD_LIBRARY_PATH" >&2
fi

HIDRAW_WRITABLE=0
for dev in /dev/hidraw*; do
    if [ -w "$dev" ]; then HIDRAW_WRITABLE=1; break; fi
done

if [ "$HIDRAW_WRITABLE" = "1" ]; then
    exec "$PYTHON" -m logimap "$@"
else
    echo "Note: escalating to sudo for hidraw access..." >&2
    # sudo strips PYTHONPATH/LD_LIBRARY_PATH from inherited env; re-set them as
    # explicit VAR=value assignments so the child sees them.
    exec sudo \
        PYTHONPATH="$PYTHONPATH" \
        LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
        "$PYTHON" -m logimap "$@"
fi
