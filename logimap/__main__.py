"""CLI entry point: logimap {gui|run|install-kwin|paint-test}."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__, _logging


def main() -> int:
    parser = argparse.ArgumentParser(prog="logimap")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=False)

    sub.add_parser("gui", help="launch profile editor")
    sub.add_parser("run", help="run the focus-aware daemon")
    sub.add_parser("install-kwin", help="load the KWin focus-emitter script")
    sub.add_parser("paint-test", help="paint hardcoded titles on all 9 keys (no daemon)")

    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="disable rotating log file at ~/.local/state/logimap/logimap.log",
    )

    args = parser.parse_args()
    if args.cmd is None:
        parser.print_help(sys.stderr)
        return 2
    log_path = _logging.setup(verbose=args.verbose, log_to_file=not args.no_log_file)
    if log_path is not None:
        logging.getLogger("logimap").info("log file: %s", log_path)

    if args.cmd == "gui":
        from .gui.app import run_gui
        return run_gui()
    if args.cmd == "run":
        from .daemon import Daemon
        return Daemon().run()
    if args.cmd == "install-kwin":
        from .focus.kwin_dbus import install_kwin_script
        return install_kwin_script()
    if args.cmd == "paint-test":
        from .device import paint_test
        return paint_test()

    return 2


if __name__ == "__main__":
    sys.exit(main())
