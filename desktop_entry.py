"""Windowed packaged entry point; the CLI and source GUI stay independently usable."""

import argparse
import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app_metadata import APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)


class LogStream(io.TextIOBase):
    """Capture windowed-build console output through the rotating log handler."""

    def write(self, text):
        if text.strip():
            logger.info("%s", text.rstrip())
        return len(text)


def configure_runtime():
    # Matplotlib must use the same Qt binding as the GUI on every platform.
    os.environ["QT_API"] = "pyside6"
    if sys.platform == "win32":
        # Bleak runs on our background asyncio thread, not a Qt/STA event loop.
        sys.coinit_flags = 0
    from PySide6.QtCore import QCoreApplication, QStandardPaths

    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)
    location = Path(
        os.environ.get("JUMPTRACK_LOG_DIR")
        or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
    )
    location.mkdir(parents=True, exist_ok=True)
    path = location / "jumptrack.log"
    handler = RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    # A shared ancestor receives failures from the GUI/session/transport modules.
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Windowed Windows/macOS executables can have no standard streams.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, LogStream())
    logger.info("Starting %s %s on %s", APP_NAME, APP_VERSION, sys.platform)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="JumpTrack desktop application")
    parser.add_argument(
        "--version", action="version", version=f"{APP_NAME} {APP_VERSION}"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Synthetic local demo without Bluetooth"
    )
    parser.add_argument(
        "--smoke-test", metavar="REPORT", type=Path, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    log_path = configure_runtime()
    try:
        if args.smoke_test:
            from desktop_smoke import run_smoke_test

            return run_smoke_test(args.smoke_test)
        from jumptrack_gui import main as gui_main

        return gui_main(["--demo"] if args.demo else [])
    except Exception:
        logger.exception("Desktop startup failed")
        if not args.smoke_test:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "JumpTrack could not start",
                f"See the diagnostic log for details:\n{log_path}",
            )
            app.quit()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
