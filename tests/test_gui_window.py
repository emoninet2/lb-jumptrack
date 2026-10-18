"""Offscreen desktop interactions; all device work uses the synthetic demo."""

import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if QT_AVAILABLE:
    from PySide6.QtCore import QDateTime, Qt, QTimer
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QLineEdit,
    )

    from jumptrack_gui import DestructiveDialog, MainWindow, configure_theme


@unittest.skipUnless(QT_AVAILABLE, "Optional GUI dependencies are not installed")
class DesktopWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_theme(cls.app)

    def setUp(self):
        self.window = MainWindow(demo=True)
        self.window.show()
        self.app.processEvents()

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.app.processEvents()
        self.assertTrue(predicate(), self.window.notice.text())

    def idle(self):
        self.wait_for(lambda: not self.window.busy)

    def connect_demo(self):
        self.window.scan()
        self.idle()
        self.assertEqual(self.window.devices.count(), 1)
        self.window.connect_device()
        self.idle()
        self.assertTrue(self.window.connected)

    def tearDown(self):
        self.idle()
        if self.window.draft:
            self.window.draft.discard()
        self.window.close()
        self.idle()
        self.assertFalse(self.window.bridge.thread.is_alive())
        self.window.deleteLater()
        self.app.processEvents()

    def test_staged_highlight_discard_and_verified_apply(self):
        self.connect_demo()
        beeps = self.window.bindings["settings.40.1"]
        beeps.setCurrentIndex(1)
        self.assertTrue(beeps.property("dirty"))
        self.assertTrue(self.window.apply_button.isEnabled())
        self.assertFalse(self.window.danger_buttons[0].isEnabled())
        self.assertEqual(self.window.bridge.session.device.groups[40][1], 0)
        self.window.discard()
        self.assertEqual(beeps.currentData(), 0)
        self.assertFalse(self.window.apply_button.isEnabled())
        beeps.setCurrentIndex(1)
        self.window.apply()
        self.idle()
        self.assertFalse(self.window.draft.pending)
        self.assertFalse(beeps.property("dirty"))
        self.assertEqual(self.window.bridge.session.device.groups[40][1], 1)
        self.assertIn("read back", self.window.notice.text())

    def test_light_theme_overrides_inherited_white_text(self):
        dark = QPalette()
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            dark.setColor(role, QColor("white"))
        self.app.setPalette(dark)
        configure_theme(self.app)
        self.app.processEvents()
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            self.assertEqual(self.app.palette().color(role).name(), "#172b43")
        self.assertEqual(
            self.window.devices.palette().color(QPalette.ColorRole.Text).name(),
            "#172b43",
        )

    def test_warning_banks_are_columns_and_altitudes_are_rows(self):
        for category in ("flight", "freefall", "canopy"):
            for bank in range(1, 5):
                controls = self.window.bindings[f"warnings.{category}.bank.{bank}"]
                grid = controls[0].parentWidget().layout()
                for altitude, control in enumerate(controls, start=1):
                    self.assertIs(grid.itemAtPosition(altitude, bank).widget(), control)

    def test_sound_buttons_play_saved_settings_and_preserve_other_edits(self):
        self.assertTrue(
            all(not button.isEnabled() for button in self.window.sound_buttons.values())
        )
        self.connect_demo()
        device = self.window.bridge.session.device
        device.play_sound = AsyncMock(wraps=device.play_sound)
        pitch = self.window.bindings["warnings.freefall.pitch"]
        pitch.setValue(5)
        self.assertFalse(self.window.sound_buttons["freefall"].isEnabled())
        self.window.test_sound("freefall")
        device.play_sound.assert_not_awaited()
        self.window.apply()
        self.idle()
        self.assertTrue(self.window.sound_buttons["freefall"].isEnabled())
        self.window.bindings["settings.40.1"].setCurrentIndex(1)
        pending = dict(self.window.draft.pending)
        for category, button in self.window.sound_buttons.items():
            button.click()
            self.idle()
            device.play_sound.assert_awaited_with(category, wait_for_response=False)
            self.assertTrue(self.window.connected)
            self.assertEqual(self.window.draft.pending, pending)
        self.assertEqual(device.play_sound.await_count, 3)

    def test_battery_status_text_and_colors(self):
        self.connect_demo()
        label = self.window.overview_labels["battery"]
        self.assertEqual(label.text(), "5.4 V · Full")
        for code, status, color in [
            (1, "Full", "#166534"),
            (2, "Half", "#854d0e"),
            (3, "Almost empty", "#9a3412"),
            (4, "Critical", "#991b1b"),
            (9, "Unknown", "#475569"),
        ]:
            self.window.draft.snapshot.details["battery_info"] = {
                "voltage": 5.1,
                "status": status,
                "status_code": code,
                "raw": f"5.1 Volt, {code}",
            }
            self.window._render_snapshot()
            self.assertEqual(label.text(), f"5.1 V · {status}")
            self.assertIn(color, label.styleSheet())
            self.assertIn("not a percentage", label.toolTip())

    def test_clock_and_confirmed_offset_controls(self):
        self.connect_demo()
        self.window.clock_edit.setDateTime(
            QDateTime.fromString("2026-10-19T14:35:22", Qt.DateFormat.ISODate)
        )
        self.window.set_clock(False)
        self.idle()
        self.assertTrue(self.window.connected)
        self.assertIn("2026-10-19T14:35:22", self.window.clock_label.text())
        self.window.offset_edit.setValue(-500)
        checked = []

        def confirm():
            dialog = QApplication.activeModalWidget()
            buttons = dialog.findChild(QDialogButtonBox)
            ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
            self.assertFalse(ok.isEnabled())
            dialog.findChild(QCheckBox).setChecked(True)
            self.assertFalse(ok.isEnabled())
            phrase = dialog.findChild(QLineEdit)
            phrase.setText("SET OFFSET ")
            self.assertFalse(ok.isEnabled())
            phrase.setText("SET OFFSET")
            self.assertTrue(ok.isEnabled())
            checked.append(True)
            ok.click()

        QTimer.singleShot(0, confirm)
        self.window.set_offset()
        self.idle()
        self.assertEqual(checked, [True])
        self.assertFalse(self.window.connected)
        self.assertIn("reset-hole", self.window.notice.text())
        self.assertFalse(self.window.offset_button.isEnabled())

    def test_failed_apply_readback_recovers_without_reconnect_or_write_retry(self):
        self.connect_demo()
        device = self.window.bridge.session.device
        read = device.get_all_warnings
        calls = 0

        async def flaky_read():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError("readback temporarily unavailable")
            return await read()

        device.get_all_warnings = flaky_read
        device.set_freefall_warnings = AsyncMock(wraps=device.set_freefall_warnings)
        control = self.window.bindings["warnings.freefall.bank.1"][0]
        control.setValue(control.value() + 100)
        self.window.apply()
        self.idle()
        self.assertTrue(self.window.connected)
        self.assertFalse(self.window.draft.pending)
        self.assertFalse(control.property("dirty"))
        self.assertFalse(self.window.apply_needs_reload)
        device.set_freefall_warnings.assert_awaited_once()
        control.setValue(control.value() + 100)
        self.assertTrue(self.window.apply_button.isEnabled())
        self.window.apply()
        self.idle()
        self.assertFalse(self.window.draft.pending)
        self.assertEqual(device.set_freefall_warnings.await_count, 2)

    def test_jump_selection_graph_units_and_export(self):
        self.connect_demo()
        self.window.tabs.setCurrentIndex(2)
        self.window.jumps.setCurrentIndex(0)
        self.idle()
        self.assertIsNotNone(self.window.current_profile)
        self.assertEqual(len(self.window.figure.axes), 2)
        self.assertIn(
            "Deployment altitude: 3400 feet", self.window.profile_summary.text()
        )
        self.window.graph_units.setCurrentText("meters")
        self.app.processEvents()
        self.assertIn(
            "Deployment altitude: 1036 meters", self.window.profile_summary.text()
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            with patch(
                "jumptrack_gui.QFileDialog.getSaveFileName",
                return_value=(str(path), "JSON"),
            ):
                self.window.export_profile()
            self.assertTrue(json.loads(path.read_text())["checksum_verified"])

    def test_confirmation_requires_phrase_and_acknowledgement_cancel_is_default(self):
        dialog = DestructiveDialog("erase-logbook", "DEMO-LOCAL", self.window)
        dialog.show()
        self.app.processEvents()
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.phrase.setText("ERASE LOGBOOK")
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.acknowledgement.setChecked(True)
        self.assertTrue(dialog.confirm.isEnabled())
        dialog.phrase.setText("ERASE LOGBOOK ")
        self.assertFalse(dialog.confirm.isEnabled())
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.deleteLater()

    def test_radio_disconnect_disables_writes_and_retains_pending_edits(self):
        self.connect_demo()
        self.window.bindings["settings.40.1"].setCurrentIndex(1)
        client = self.window.bridge.session.device.client
        self.window.bridge.loop.call_soon_threadsafe(
            setattr, client, "is_connected", False
        )
        self.wait_for(lambda: not self.window.connected, timeout=3)
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertEqual(self.window.draft.pending["settings.40.1"], 1)
        self.assertFalse(self.window.bindings["settings.40.1"].isEnabled())
        self.window.connect_device()
        self.idle()
        self.assertTrue(self.window.connected)
        self.assertEqual(self.window.draft.pending["settings.40.1"], 1)
        self.assertTrue(self.window.bindings["settings.40.1"].isEnabled())
        self.window.apply()
        self.idle()
        self.assertTrue(self.window.connected)
        self.window.bindings["settings.40.1"].setCurrentIndex(0)
        self.assertTrue(self.window.apply_button.isEnabled())
