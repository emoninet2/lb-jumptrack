"""Exercise the installed bundle's demo, Qt plugins and charts without Bluetooth."""

import json
import logging
import platform
import time
from pathlib import Path

from app_metadata import APP_VERSION

logger = logging.getLogger(__name__)


def run_smoke_test(report_path):
    from bleak.backends.client import get_platform_client_backend_type
    from bleak.backends.scanner import get_platform_scanner_backend_type
    from PySide6.QtWidgets import QApplication

    from jumptrack_gui import MainWindow, configure_theme

    app = QApplication.instance() or QApplication([])
    configure_theme(app)
    window = MainWindow(demo=True)
    window.show()
    checks = []

    def idle():
        deadline = time.monotonic() + 15
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        if window.busy:
            raise TimeoutError("Demo operation timed out")

    def check(condition, name):
        if not condition:
            raise RuntimeError(f"Packaged smoke test failed: {name}")
        checks.append(name)

    result = {
        "version": APP_VERSION,
        "platform": platform.platform(),
        "checks": checks,
        "ok": False,
    }
    try:
        # Resolve/import the native backend without instantiating an adapter or
        # requesting Bluetooth access. Demo alone would not exercise this.
        get_platform_client_backend_type()
        get_platform_scanner_backend_type()
        check(True, "native BLE backend imports (no hardware access)")
        window.scan()
        idle()
        check(window.devices.count() == 1, "synthetic discovery")
        window.connect_device()
        idle()
        check(window.connected, "demo session")
        check("Full" in window.overview_labels["battery"].text(), "battery decoding")
        window.jumps.setCurrentIndex(0)
        idle()
        check(
            window.current_profile is not None and len(window.figure.axes) == 2,
            "profile decoding and QtAgg charts",
        )
        control = window.bindings["settings.40.1"]
        control.setCurrentIndex(1)
        check(bool(window.draft.pending), "staged edits")
        window.apply()
        idle()
        check(
            not window.draft.pending and window.connected,
            "verified apply and persistent connection",
        )
        window.sound_buttons["freefall"].click()
        idle()
        check(window.connected, "simulated sound playback")
        image = window.grab()
        check(not image.isNull(), "Qt rendering")
        result["ok"] = True
    except Exception as exc:
        logger.exception("Packaged demo smoke test failed")
        result["error"] = str(exc)
    finally:
        if not window.busy:
            if window.draft:
                window.draft.discard()
            window.close()
            idle()
        if window.bridge.thread.is_alive():
            window.bridge.stop()
        if window.bridge.thread.is_alive():
            result["ok"] = False
            result["error"] = "Bluetooth worker did not stop"
        else:
            result["checks"].append("worker shutdown")
        Path(report_path).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if result["ok"] else 1
