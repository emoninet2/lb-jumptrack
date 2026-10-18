"""JumpTrack desktop GUI. Run with --demo to explore without Bluetooth or writes."""

import argparse
import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QDateTime, QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui_backend import CONFIRMATIONS, DeviceSession, Draft, records
from profile_decoder import decode_profile, format_profile_summary, parse_profile

logger = logging.getLogger(__name__)


STYLE = """
QMainWindow, QDialog {background:#f3f6fa; color:#172b43;}
QWidget {font-family: "DejaVu Sans"; font-size:13px; color:#172b43;}
QWidget:disabled {color:#65788b;}
QToolTip {background:#172b43; color:white; border:1px solid #516780;}
QComboBox QAbstractItemView {background:white; color:#172b43; selection-background-color:#173f66; selection-color:white;}
QLabel#title {font-size:28px; font-weight:700; color:#112f4d;}
QLabel#subtitle {color:#516780;}
QLabel#notice {background:#e6eff9; padding:10px; border-radius:6px; color:#23466b;}
QLabel#pending {font-weight:600; color:#8a5700;}
QGroupBox {background:white; border:1px solid #d8e2ed; border-radius:8px; margin-top:14px; padding:18px 12px 12px; font-weight:600;}
QGroupBox::title {subcontrol-origin:margin; left:14px; padding:0 5px;}
QTabWidget::pane {border:1px solid #d8e2ed; background:white; border-radius:6px;}
QTabBar::tab {background:#e7edf5; padding:12px 22px; border:0; margin-right:3px;}
QTabBar::tab:selected {background:#173f66; color:white;}
QTabBar::tab:!selected:hover {background:#d9e6f3;}
QPushButton {padding:9px 14px; background:white; border:1px solid #bccddd; border-radius:5px;}
QPushButton:hover {background:#eaf2fa;}
QPushButton:disabled {color:#8796a5; background:#edf1f5;}
QPushButton#primary {background:#116d82; color:white; border:1px solid #116d82; font-weight:600;}
QPushButton#primary:disabled {background:#a6bec5; border-color:#a6bec5;}
QPushButton#danger {color:#a12636; border-color:#d9a0a7;}
QComboBox, QLineEdit, QSpinBox, QDateTimeEdit {padding:7px; border:1px solid #bdccdc; border-radius:4px; background:white; min-height:20px;}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDateTimeEdit:focus {border:1px solid #116d82;}
QLabel#metric {font-size:22px; font-weight:600; color:#173f66;}
QComboBox[dirty="true"], QSpinBox[dirty="true"] {border:2px solid #d69722; background:#fff7e5;}
QPlainTextEdit {border:1px solid #d8e2ed; background:#fbfcfe; padding:8px;}
QProgressBar {border:0; background:#e4ecf4; max-height:4px;}
QProgressBar::chunk {background:#16849a;}
"""


def configure_theme(app):
    """Keep native controls readable even when the desktop uses a dark palette."""
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f3f6fa",
        QPalette.ColorRole.WindowText: "#172b43",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#edf2f7",
        QPalette.ColorRole.Text: "#172b43",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#172b43",
        QPalette.ColorRole.ToolTipBase: "#172b43",
        QPalette.ColorRole.ToolTipText: "#ffffff",
        QPalette.ColorRole.Highlight: "#173f66",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#65788b",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#65788b"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


class AsyncBridge(QObject):
    completed = Signal(int, object, str, bool)
    progress = Signal(str)
    connection_lost = Signal()

    def __init__(self, demo=False):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError("Bluetooth worker did not start")
        if demo:
            from gui_demo import DemoSession

            self.session = DemoSession(progress=self.progress.emit)
        else:
            self.session = DeviceSession(progress=self.progress.emit)
        self.next_id = 0
        self._was_connected = False
        asyncio.run_coroutine_threadsafe(self._watch_connection(), self.loop)

    async def _watch_connection(self):
        while True:
            await asyncio.sleep(0.5)
            if self.session.connected:
                self._was_connected = True
            elif self._was_connected:
                self._was_connected = False
                self.connection_lost.emit()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self.loop.close()

    def submit(self, coroutine):
        self.next_id += 1
        job_id = self.next_id

        async def execute():
            try:
                value, error = await coroutine, ""
            except Exception as exc:
                logger.exception("Desktop background operation failed")
                value, error = None, str(exc)
            connected = self.session.connected
            if connected:
                self._was_connected = True
            return value, error, connected

        future = asyncio.run_coroutine_threadsafe(execute(), self.loop)

        def done(result):
            value, error, connected = result.result()
            self.completed.emit(job_id, value, error, connected)

        future.add_done_callback(done)
        return job_id

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)


class DestructiveDialog(QDialog):
    def __init__(self, action, address, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm destructive action")
        self.setMinimumWidth(470)
        phrase = CONFIRMATIONS[action]
        layout = QVBoxLayout(self)
        title = QLabel(
            "Erase entire logbook"
            if action == "erase-logbook"
            else "Restore factory settings"
        )
        title.setStyleSheet("font-size:20px;font-weight:700;color:#a12636;")
        layout.addWidget(title)
        label = QLabel(
            f"Device: {address}\n\nThis action cannot be undone. Factory reset may also remove logbook data.\nExport anything you need before continuing."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.acknowledgement = QCheckBox(
            "I understand this can permanently remove device data."
        )
        layout.addWidget(self.acknowledgement)
        layout.addWidget(QLabel(f"Type exactly: {phrase}"))
        self.phrase = QLineEdit()
        self.phrase.setPlaceholderText(phrase)
        layout.addWidget(self.phrase)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.confirm = buttons.addButton(
            "Confirm destructive action", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.confirm.setObjectName("danger")
        self.confirm.setEnabled(False)
        self.confirm.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.rejected.connect(self.reject)
        self.confirm.clicked.connect(self.accept)
        self.phrase.textChanged.connect(
            lambda _text: self.confirm.setEnabled(
                self.phrase.text() == phrase and self.acknowledgement.isChecked()
            )
        )
        self.acknowledgement.toggled.connect(
            lambda _value: self.confirm.setEnabled(
                self.phrase.text() == phrase and self.acknowledgement.isChecked()
            )
        )
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self, *, demo=False, bridge=None):
        super().__init__()
        self.demo = demo
        self.bridge = bridge or AsyncBridge(demo)
        self.bridge.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.progress.connect(self._progress)
        self.bridge.connection_lost.connect(self._connection_lost)
        self.draft = None
        self.busy = False
        self.apply_needs_reload = False
        self.connected = False
        self.rendering = False
        self.jobs = {}
        self.bindings = {}
        self.profile_cache = {}
        self.current_profile = None
        self.closing_ready = False
        self.setWindowTitle("JumpTrack Desktop" + (" — Demo" if demo else ""))
        self.resize(1220, 880)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 18)
        heading = QHBoxLayout()
        title = QLabel("JumpTrack")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        self.connection_label = QLabel(
            "DEMO · no Bluetooth or hardware writes" if demo else "Disconnected"
        )
        self.connection_label.setObjectName("subtitle")
        heading.addWidget(self.connection_label)
        layout.addLayout(heading)
        self.notice = QLabel(
            "Scan for your device, select it, and connect. Edits stay local until Apply changes."
        )
        self.notice.setWordWrap(True)
        self.notice.setObjectName("notice")
        layout.addWidget(self.notice)
        connection = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter device name or address")
        self.filter.setMaximumWidth(250)
        self.all_devices = QCheckBox("All devices")
        self.scan_button = QPushButton("Scan Bluetooth")
        self.scan_button.clicked.connect(self.scan)
        self.devices = QComboBox()
        self.devices.setMinimumWidth(290)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self.connect_device)
        self.refresh_button = QPushButton("Reload device")
        self.refresh_button.clicked.connect(self.refresh)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_device)
        for widget in (
            self.filter,
            self.all_devices,
            self.scan_button,
            self.devices,
            self.connect_button,
            self.refresh_button,
            self.disconnect_button,
        ):
            connection.addWidget(widget)
        layout.addLayout(connection)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._overview()
        self._warnings()
        self._logbook()
        self._settings()
        self._maintenance()
        self._diagnostics()
        footer = QHBoxLayout()
        self.pending_label = QLabel("No unsaved changes")
        self.pending_label.setObjectName("pending")
        footer.addWidget(self.pending_label)
        footer.addStretch()
        self.discard_button = QPushButton("Discard changes")
        self.discard_button.clicked.connect(self.discard)
        self.apply_button = QPushButton("Apply changes")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.discard_button)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)
        self.statusBar().showMessage("Ready — no device connected")
        self._sync()

    def _page(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        self.tabs.addTab(page, title)
        return page, layout

    def _overview(self):
        _, layout = self._page("Overview")
        layout.addWidget(QLabel("Device at a glance"))
        grid = QGridLayout()
        self.overview_labels = {}
        for i, (key, title) in enumerate(
            [
                ("device", "Device information"),
                ("jump_count", "Jump counter"),
                ("battery", "Battery"),
                ("freefall_total", "Total freefall time"),
            ]
        ):
            card = QGroupBox(title)
            inside = QVBoxLayout(card)
            value = QLabel("Connect a device to load")
            if key in ("jump_count", "freefall_total"):
                value.setObjectName("metric")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            inside.addWidget(value)
            self.overview_labels[key] = value
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid)
        note = QLabel(
            "Read-only connection: settings and warnings are loaded automatically.\nUnavailable fields stay disabled. Select a jump in Logbook to download its profile."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def _combo(self, key, choices):
        widget = QComboBox()
        for value, label in choices:
            widget.addItem(label, value)
        widget.currentIndexChanged.connect(
            lambda _index, k=key, w=widget: self._edit(k, w.currentData())
        )
        self.bindings[key] = widget
        return widget

    def _spin(self, key, low=0, high=2147483647):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.valueChanged.connect(lambda value, k=key: self._edit(k, value))
        self.bindings[key] = widget
        return widget

    def _warnings(self):
        _, layout = self._page("Warnings")
        self.warning_units = QLabel(
            "Altitudes use the device’s loaded units. Zero values are preserved."
        )
        layout.addWidget(self.warning_units)
        inner = QTabWidget()
        self.sound_buttons = {}
        layout.addWidget(inner)
        for category in ("flight", "freefall", "canopy"):
            pane = QWidget()
            box = QVBoxLayout(pane)
            inner.addTab(pane, category.capitalize())
            bank_group = QGroupBox("Warning banks")
            grid = QGridLayout(bank_group)
            for column, text in enumerate(
                ["Altitude", "Bank 1", "Bank 2", "Bank 3", "Bank 4"]
            ):
                grid.addWidget(QLabel(text), 0, column)
            for row in range(1, 5):
                grid.addWidget(QLabel(f"Altitude {row}"), row, 0)
            for bank in range(1, 5):
                key = f"warnings.{category}.bank.{bank}"
                controls = []
                for column in range(4):
                    control = QSpinBox()
                    control.setRange(0, 2147483647)
                    control.setMinimumWidth(110)
                    control.valueChanged.connect(lambda _v, k=key: self._edit_bank(k))
                    controls.append(control)
                    grid.addWidget(control, column + 1, bank)
                self.bindings[key] = controls
            box.addWidget(bank_group)
            group = QGroupBox("Sound and active bank")
            form = QFormLayout(group)
            form.addRow(
                "Active bank",
                self._combo(
                    f"warnings.{category}.active_bank",
                    [(i, f"Bank {i}") for i in range(1, 5)],
                ),
            )
            form.addRow("Pitch (1–7)", self._spin(f"warnings.{category}.pitch", 1, 7))
            form.addRow(
                "Volume (1–10)", self._spin(f"warnings.{category}.volume", 1, 10)
            )
            test = QPushButton("Test saved sound")
            test.clicked.connect(lambda _checked=False, c=category: self.test_sound(c))
            self.sound_buttons[category] = test
            form.addRow(test)
            note = QLabel(
                "Plays on the device using saved pitch/volume. Apply sound edits first. Playback reserves the connection for 25 seconds."
            )
            note.setWordWrap(True)
            form.addRow(note)
            box.addWidget(group)
            box.addStretch()

    def _settings(self):
        page, _ = self._page("Settings")
        layout = page.layout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        groups = [
            (
                "General",
                [
                    ("Button beeps", "settings.40.1", [(0, "Off"), (1, "On")]),
                    (
                        "Dive type",
                        "settings.40.2",
                        [
                            (0, "Default"),
                            (1, "3 seconds"),
                            (2, "Slow"),
                            (3, "Super slow"),
                        ],
                    ),
                    ("Flat-line", "settings.41.0", [(0, "Off"), (1, "On")]),
                ],
            ),
            (
                "Measurement units",
                [
                    ("Distance", "distance_unit", [(0, "Feet"), (1, "Meters")]),
                    ("Speed", "speed_unit", [(0, "mph"), (1, "km/h")]),
                    (
                        "Temperature",
                        "settings.40.3",
                        [(0, "Celsius"), (1, "Fahrenheit")],
                    ),
                ],
            ),
            (
                "Bluetooth",
                [
                    ("Mode", "settings.40.0", [(0, "Automatic"), (1, "Economy")]),
                    ("Tap to enable", "settings.41.1", [(0, "Off"), (1, "On")]),
                ],
            ),
            (
                "Display",
                [
                    ("Date format", "settings.42.0", [(0, "European"), (1, "US")]),
                    (
                        "Show time under canopy",
                        "settings.42.2",
                        [(0, "Off"), (1, "On")],
                    ),
                    ("Display timeout", "settings.42.1", None),
                    ("Backlight value", "settings.42.3", None),
                ],
            ),
        ]
        for index, (title, fields) in enumerate(groups):
            card = QGroupBox(title)
            form = QFormLayout(card)
            for label, key, choices in fields:
                form.addRow(
                    label, self._combo(key, choices) if choices else self._spin(key)
                )
            grid.addWidget(card, index // 2, index % 2)
        note = QLabel(
            "Amber fields have unsaved edits. Apply distance-unit changes separately from warning edits.\nTAS/SAS selection is unavailable; no verified command has been identified."
        )
        note.setWordWrap(True)
        clock = QGroupBox("Device date and time")
        form = QFormLayout(clock)
        self.clock_label = QLabel("Not loaded")
        form.addRow("Last read", self.clock_label)
        self.clock_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.clock_edit.setCalendarPopup(True)
        self.clock_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        form.addRow("Local date/time", self.clock_edit)
        self.clock_button = QPushButton("Set device date/time")
        self.clock_button.clicked.connect(lambda: self.set_clock(False))
        self.sync_clock_button = QPushButton("Sync with computer now")
        self.sync_clock_button.clicked.connect(lambda: self.set_clock(True))
        form.addRow(self.clock_button)
        form.addRow(self.sync_clock_button)
        grid.addWidget(clock, 2, 0)
        offset = QGroupBox("Altitude offset")
        form = QFormLayout(offset)
        self.offset_label = QLabel("Not loaded")
        form.addRow("Current offset", self.offset_label)
        self.offset_edit = QSpinBox()
        self.offset_edit.setRange(-9900, 9900)
        form.addRow("New offset", self.offset_edit)
        warning = QLabel(
            "Setting an offset enters Flight Mode and disables Bluetooth. Your PROTRACK 3 may require its reset-hole procedure before you can use it again."
        )
        warning.setWordWrap(True)
        form.addRow(warning)
        self.offset_button = QPushButton("Set altitude offset…")
        self.offset_button.clicked.connect(self.set_offset)
        form.addRow(self.offset_button)
        grid.addWidget(offset, 2, 1)
        grid.addWidget(note, 3, 0, 1, 2)
        grid.setRowStretch(4, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _logbook(self):
        _, layout = self._page("Logbook")
        row = QHBoxLayout()
        row.addWidget(QLabel("Jump"))
        self.jumps = QComboBox()
        self.jumps.setMinimumWidth(310)
        self.jumps.currentIndexChanged.connect(self.select_jump)
        row.addWidget(self.jumps)
        self.graph_units = QComboBox()
        self.graph_units.addItems(["feet", "meters"])
        self.graph_units.currentTextChanged.connect(self.render_profile)
        self.graph_speed = QComboBox()
        self.graph_speed.addItems(["mph", "kmh", "fps", "mps"])
        self.graph_speed.currentTextChanged.connect(self.render_profile)
        row.addWidget(self.graph_units)
        row.addWidget(self.graph_speed)
        row.addStretch()
        open_button = QPushButton("Open saved profile…")
        open_button.clicked.connect(self.open_profile)
        row.addWidget(open_button)
        self.export_button = QPushButton("Export JSON…")
        self.export_button.clicked.connect(self.export_profile)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.profile_summary = QLabel(
            "Select a jump to load its recorded information and profile."
        )
        self.profile_summary.setWordWrap(True)
        self.profile_summary.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.profile_summary)
        self.figure = Figure(figsize=(9, 5), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, 1)
        self.figure.text(
            0.5,
            0.5,
            "Select a jump to view altitude and vertical speed",
            ha="center",
            color="#61788f",
        )

    def _maintenance(self):
        _, layout = self._page("Maintenance")
        label = QLabel(
            "Destructive actions are separate from Apply changes.\nEach action requires an acknowledgement and an exact typed phrase for the connected device."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.danger_buttons = []
        for action, title in [
            ("erase-logbook", "Erase entire logbook…"),
            ("factory-reset", "Restore factory settings…"),
        ]:
            card = QGroupBox(title.rstrip("…"))
            inside = QVBoxLayout(card)
            inside.addWidget(
                QLabel(
                    "Permanently removes all recorded jumps."
                    if action == "erase-logbook"
                    else "Restores device defaults and may remove recorded jumps."
                )
            )
            button = QPushButton(title)
            button.setObjectName("danger")
            button.clicked.connect(lambda _checked=False, a=action: self.destructive(a))
            inside.addWidget(button)
            self.danger_buttons.append(button)
            layout.addWidget(card)
        unavailable = QPushButton("Delete selected jump — unavailable")
        unavailable.setEnabled(False)
        unavailable.setToolTip(
            "The verified protocol has no individual jump-delete command."
        )
        layout.addWidget(unavailable)
        layout.addWidget(
            QLabel(
                "Individual jump deletion is not offered because no verified command exists."
            )
        )
        layout.addStretch()

    def _diagnostics(self):
        _, layout = self._page("Diagnostics")
        layout.addWidget(
            QLabel("Latest device snapshot and read errors. This data stays local.")
        )
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        layout.addWidget(self.diagnostics)

    def _submit(self, message, coroutine, callback):
        if self.busy:
            coroutine.close()
            return
        self.busy = True
        self.statusBar().showMessage(message)
        self.notice.setText(message)
        job_id = self.bridge.submit(coroutine)
        self.jobs[job_id] = callback
        self._sync()

    @Slot(int, object, str, bool)
    def _completed(self, job_id, result, error, connected):
        callback = self.jobs.pop(job_id, None)
        self.busy = False
        self.connected = connected
        if error:
            self.notice.setText(error)
            self.diagnostics.appendPlainText("\nOperation failed: " + error)
            self.statusBar().showMessage("Operation failed — no automatic retry")
        elif callback:
            try:
                callback(result)
            except Exception as exc:
                logger.exception("Desktop result rendering failed")
                self.notice.setText(str(exc))
                self.diagnostics.appendPlainText(str(exc))
        self._sync()

    @Slot(str)
    def _progress(self, message):
        self.statusBar().showMessage(message)

    @Slot()
    def _connection_lost(self):
        if self.connected:
            self.connected = False
            self.notice.setText(
                "Bluetooth disconnected. Pending edits remain local; reconnect to reload device values."
            )
            self.statusBar().showMessage("Device disconnected")
            self._sync()

    def _sync(self):
        available = self.connected and not self.busy
        for widget in (self.scan_button, self.filter, self.all_devices, self.devices):
            widget.setEnabled(not self.busy and not self.connected)
        self.connect_button.setEnabled(
            not self.busy and not self.connected and self.devices.count() > 0
        )
        self.refresh_button.setEnabled(available)
        self.disconnect_button.setEnabled(available)
        self.jumps.setEnabled(available and self.jumps.count() > 0)
        self.progress_bar.setVisible(self.busy)
        for key, binding in self.bindings.items():
            enabled = (
                available
                and self.draft is not None
                and key in self.draft.snapshot.values
                and (
                    ".bank." not in key or "distance_unit" in self.draft.snapshot.values
                )
            )
            for control in binding if isinstance(binding, list) else [binding]:
                control.setEnabled(enabled)
        pending = len(self.draft.pending) if self.draft else 0
        for category, button in self.sound_buttons.items():
            sound_keys = [f"warnings.{category}.{name}" for name in ("pitch", "volume")]
            button.setEnabled(
                available
                and not self.apply_needs_reload
                and self.draft is not None
                and all(
                    key in self.draft.snapshot.values and key not in self.draft.pending
                    for key in sound_keys
                )
            )
        separate = available and pending == 0 and not self.apply_needs_reload
        self.clock_edit.setEnabled(separate)
        self.clock_button.setEnabled(separate)
        self.sync_clock_button.setEnabled(separate)
        units_loaded = (
            self.draft is not None and "distance_unit" in self.draft.snapshot.values
        )
        self.offset_edit.setEnabled(separate and units_loaded)
        self.offset_button.setEnabled(separate and units_loaded)
        self.pending_label.setText(
            f"{pending} unsaved change" + ("s" if pending != 1 else "")
            if pending
            else "No unsaved changes"
        )
        self.apply_button.setEnabled(
            available and pending > 0 and not self.apply_needs_reload
        )
        self.discard_button.setEnabled(not self.busy and pending > 0)
        for button in self.danger_buttons:
            button.setEnabled(available and pending == 0)
        self.export_button.setEnabled(
            self.current_profile is not None and not self.busy
        )
        if not self.demo:
            self.connection_label.setText(
                ("Connected · " + self.draft.snapshot.address)
                if self.connected and self.draft
                else "Disconnected"
            )

    def scan(self):
        self._submit(
            "Scanning nearby Bluetooth devices…",
            self.bridge.session.scan(
                all_devices=self.all_devices.isChecked(), query=self.filter.text()
            ),
            self._scanned,
        )

    def _scanned(self, rows):
        self.devices.clear()
        for row in rows:
            self.devices.addItem(
                f"{row['name']} · {row['address']} · {row['rssi']} dBm", row["address"]
            )
        self.notice.setText(
            f"{len(rows)} matching device(s). Select one and connect."
            if rows
            else "No matching devices found. Enable Bluetooth on the device, or try All devices."
        )
        self.statusBar().showMessage("Scan complete")

    def _discard_for(self, action):
        if not self.draft or not self.draft.pending:
            return True
        return (
            QMessageBox.question(
                self,
                "Unsaved changes",
                f"{action} will discard your local edits. Continue?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def connect_device(self):
        address = self.devices.currentData()
        if address:
            preserve = (
                self.draft is not None
                and self.draft.snapshot.address == address
                and bool(self.draft.pending)
            )
            if not preserve and not self._discard_for("Connecting"):
                return
            self.profile_cache.clear()
            self.current_profile = None
            self._submit(
                "Connecting and reading device information…",
                self.bridge.session.connect(address),
                lambda snapshot: self._loaded(snapshot, preserve=preserve),
            )

    def _loaded(self, snapshot, preserve=False):
        self.apply_needs_reload = False
        self.current_profile = None
        self.profile_summary.setText(
            "Select a jump to load its recorded information and profile."
        )
        self.figure.clear()
        self.figure.text(
            0.5,
            0.5,
            "Select a jump to view altitude and vertical speed",
            ha="center",
            color="#61788f",
        )
        self.canvas.draw_idle()
        if preserve:
            self.draft.reconcile(snapshot)
        else:
            self.draft = Draft(snapshot)
        self._render_snapshot()
        self.notice.setText(
            "Loaded device information. Changes stay local until Apply changes."
            + (
                " Some fields are unavailable; see Diagnostics."
                if snapshot.errors
                else ""
            )
        )
        self.statusBar().showMessage("Device loaded; no settings written")
        if preserve and self.draft.pending:
            self.notice.setText(
                "Reconnected. Pending edits are preserved locally; review them before Apply changes."
            )

    def refresh(self):
        if self.draft:
            self._submit(
                "Reloading settings and verifying pending edits…",
                self.bridge.session.reload_settings(self.draft.snapshot),
                self._settings_reloaded,
            )

    def _settings_reloaded(self, snapshot):
        self.apply_needs_reload = False
        self.draft.reconcile(snapshot)
        self._render_snapshot()
        self.notice.setText(
            "Device values reloaded. Remaining highlighted edits are still local; review before Apply."
            if self.draft.pending
            else "Device values verified. You can continue editing."
        )

    def disconnect_device(self):
        if self._discard_for("Disconnecting"):
            self._submit(
                "Disconnecting…",
                self.bridge.session.disconnect(),
                lambda _r: self._disconnected(),
            )

    def _disconnected(self):
        if self.draft:
            self.draft.discard()
        self.notice.setText("Disconnected. Displayed data is the last loaded snapshot.")
        self.statusBar().showMessage("Disconnected")
        self._paint_dirty()

    def _render_snapshot(self):
        self.rendering = True
        try:
            snapshot = self.draft.snapshot
            self.clock_label.setText(snapshot.details.get("datetime", "Not reported"))
            unit = snapshot.values.get("distance_unit")
            suffix = (
                " feet"
                if unit == 0
                else " metres"
                if unit == 1
                else " (units unavailable)"
            )
            self.offset_label.setText(
                str(snapshot.details.get("altitude_offset", "Not reported")) + suffix
            )
            self.offset_edit.setRange(
                -(9900 if unit == 0 else 3000), 9900 if unit == 0 else 3000
            )
            self.offset_edit.setSuffix(suffix)
            self.offset_edit.setValue(snapshot.details.get("altitude_offset", 0))
            for key, binding in self.bindings.items():
                value = self.draft.value(key)
                if isinstance(binding, list):
                    for i, widget in enumerate(binding):
                        widget.setValue(value[i] if value is not None else 0)
                elif isinstance(binding, QComboBox):
                    binding.setCurrentIndex(binding.findData(value))
                else:
                    binding.setValue(value if value is not None else 0)
                for widget in binding if isinstance(binding, list) else [binding]:
                    widget.setToolTip(
                        "Unavailable or unrecognized on this device"
                        if value is None
                        else "Edits are local until Apply changes"
                    )
            for key, label in self.overview_labels.items():
                text = str(snapshot.details.get(key, "Not reported"))
                if key == "battery":
                    info = snapshot.details.get("battery_info", {})
                    status = info.get("status", "Unknown")
                    voltage = info.get("voltage")
                    text = (
                        f"{voltage:g} V · {status}"
                        if voltage is not None
                        else "Battery status unknown"
                    )
                    colors = {
                        "Full": ("#166534", "#dcfce7"),
                        "Half": ("#854d0e", "#fef9c3"),
                        "Almost empty": ("#9a3412", "#ffedd5"),
                        "Critical": ("#991b1b", "#fee2e2"),
                    }
                    foreground, background = colors.get(status, ("#475569", "#e2e8f0"))
                    label.setStyleSheet(
                        f"color:{foreground}; background:{background}; padding:10px; border-radius:5px; font-weight:600;"
                    )
                    label.setToolTip(
                        f"Device-reported battery status; not a percentage.\nRaw: {info.get('raw') or 'Not reported'}\nStatus code: {info.get('status_code')}"
                    )
                if key == "jump_count":
                    counter = records(snapshot.raw["Jump count"]).get(39)
                    if counter:
                        text = str(counter[3])
                if key in ("device", "jump_count"):
                    text = "\n".join(
                        line
                        for line in text.splitlines()
                        if not line.startswith("CheckSum")
                        and line not in ("EOF", "Who?", "Get Jump Counter")
                    )
                label.setText(text)
            unit = {0: "feet", 1: "meters"}.get(
                snapshot.values.get("distance_unit"), "unknown units"
            )
            self.warning_units.setText(
                f"Warning altitudes • {unit} as loaded from the device. Zero values are preserved."
            )
            selected = self.jumps.currentData()
            self.jumps.clear()
            for jump in snapshot.jumps:
                self.jumps.addItem(
                    f"Jump {jump['jump_number']} · {jump['timestamp'].replace('T', ' ')}",
                    jump["jump_number"],
                )
            if self.jumps.findData(selected) >= 0:
                self.jumps.setCurrentIndex(self.jumps.findData(selected))
            else:
                self.jumps.setCurrentIndex(-1)
            self.diagnostics.setPlainText(
                json.dumps(
                    {
                        "address": snapshot.address,
                        "errors": snapshot.errors,
                        "responses": snapshot.raw,
                    },
                    indent=2,
                )
            )
        finally:
            self.rendering = False
        self._paint_dirty()
        self._sync()

    def _edit(self, key, value):
        if (
            self.rendering
            or self.busy
            or not self.connected
            or self.draft is None
            or value is None
        ):
            return
        try:
            self.draft.set(key, value)
        except ValueError as exc:
            self.notice.setText(str(exc))
        self._paint_dirty()
        self._sync()

    def _edit_bank(self, key):
        self._edit(key, tuple(widget.value() for widget in self.bindings[key]))

    def _paint_dirty(self):
        for key, binding in self.bindings.items():
            for widget in binding if isinstance(binding, list) else [binding]:
                widget.setProperty(
                    "dirty", bool(self.draft and key in self.draft.pending)
                )
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def discard(self):
        if self.draft:
            self.draft.discard()
            self._render_snapshot()
            self.notice.setText("Local edits discarded. No device writes sent.")

    def apply(self):
        if self.draft and self.draft.pending:
            self._submit(
                "Checking current device values before applying…",
                self.bridge.session.apply(
                    self.draft.snapshot, dict(self.draft.pending)
                ),
                self._applied,
            )

    def _applied(self, result):
        self.apply_needs_reload = bool(result.error)
        self.draft.reconcile(result.snapshot)
        self._render_snapshot()
        self.notice.setText(
            result.error or "All changes applied and read back successfully."
        )
        self.statusBar().showMessage(
            result.error or f"{len(result.verified)} setting(s) verified"
        )
        if result.error:
            self.diagnostics.appendPlainText("\nApply verification: " + result.error)
            if self.connected:
                self._submit(
                    "Checking device values after incomplete verification (read only)…",
                    self.bridge.session.reload_settings(self.draft.snapshot),
                    self._settings_reloaded,
                )

    def destructive(self, action):
        if self.busy or not self.connected or not self.draft or self.draft.pending:
            return
        address = self.draft.snapshot.address
        dialog = DestructiveDialog(action, address, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._submit(
                "Performing confirmed destructive action…",
                self.bridge.session.destructive(action, dialog.phrase.text(), address),
                self._destroyed,
            )

    def set_clock(self, sync):
        if (
            self.busy
            or not self.connected
            or not self.draft
            or self.draft.pending
            or self.apply_needs_reload
        ):
            return
        value = (
            datetime.now().replace(microsecond=0)
            if sync
            else self.clock_edit.dateTime()
            .toPython()
            .replace(tzinfo=None, microsecond=0)
        )
        self._submit(
            "Setting and verifying device date/time…",
            self.bridge.session.set_clock(self.draft.snapshot, value),
            self._clock_set,
        )

    def test_sound(self, category):
        button = self.sound_buttons.get(category)
        if button is None or not button.isEnabled() or self.busy:
            return
        self._submit(
            f"Testing saved {category} sound on the device…",
            self.bridge.session.test_sound(self.draft.snapshot, category),
            lambda _result: self.notice.setText(
                "Demo sound test completed; no audio or Bluetooth used."
                if self.demo
                else f"{category.capitalize()} playback window finished. Listen on the device to confirm pitch and loudness."
            ),
        )

    def _clock_set(self, snapshot):
        self._settings_reloaded(snapshot)
        self.notice.setText("Device date/time set and read back successfully.")

    def set_offset(self):
        if (
            self.busy
            or not self.connected
            or not self.draft
            or self.draft.pending
            or self.apply_needs_reload
        ):
            return
        value = self.offset_edit.value()
        dialog = QDialog(self)
        dialog.setWindowTitle("Confirm altitude offset")
        layout = QVBoxLayout(dialog)
        text = QLabel(
            f"Device: {self.draft.snapshot.address}\nSet offset: {value}{self.offset_edit.suffix()}\n\nThis enters Flight Mode and disables Bluetooth.\nYour PROTRACK 3 may need the reset-hole procedure afterward.\nThe Android app says the offset lasts 14 hours if no jump is made.\n\nApply or discard other edits first. This action cannot be verified immediately."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        acknowledge = QCheckBox("I understand the device will become unavailable")
        layout.addWidget(acknowledge)
        phrase = QLineEdit()
        phrase.setPlaceholderText("Type SET OFFSET")
        layout.addWidget(phrase)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        confirm.setText("Set offset and end session")
        confirm.setEnabled(False)
        confirm.setAutoDefault(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)

        def gate():
            confirm.setEnabled(
                acknowledge.isChecked() and phrase.text() == "SET OFFSET"
            )

        acknowledge.toggled.connect(gate)
        phrase.textChanged.connect(gate)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._submit(
                "Sending altitude offset once; ending Bluetooth session…",
                self.bridge.session.set_offset(
                    self.draft.snapshot, value, phrase.text()
                ),
                self._offset_sent,
            )

    def _offset_sent(self, _result):
        self.notice.setText(
            "Offset command sent once; not read back. Bluetooth session ended. Your PROTRACK 3 may require its reset-hole procedure before further use. Reconnect later to inspect the offset."
        )
        self.statusBar().showMessage("Offset submitted; device unavailable; no retry")

    def _destroyed(self, _result):
        self.profile_cache.clear()
        self.current_profile = None
        self.jumps.clear()
        self.profile_summary.setText(
            "Device action completed. Reconnect to load current data."
        )
        self.figure.clear()
        self.canvas.draw_idle()
        self.notice.setText(
            "Confirmed action sent. Device disconnected; reconnect to reload current state."
        )
        self.statusBar().showMessage("Reconnect to verify device state")

    def select_jump(self, _index=None):
        if self.rendering or self.busy or not self.connected:
            return
        number = self.jumps.currentData()
        if number is None:
            return
        key = (self.draft.snapshot.address, number)
        if key in self.profile_cache:
            self._profile_loaded(self.profile_cache[key])
            return

        def loaded(result):
            self.profile_cache[key] = result
            self._profile_loaded(result)

        self._submit(
            f"Loading jump {number}…", self.bridge.session.profile(number), loaded
        )

    def _profile_loaded(self, result):
        self.current_profile = result
        self.render_profile()
        self.notice.setText(
            "Profile loaded and checksum verified. TAS/SAS recording mode remains unknown."
        )
        self.statusBar().showMessage("Profile loaded")

    def render_profile(self, _text=None):
        if self.current_profile is None:
            return
        try:
            decoded = decode_profile(
                self.current_profile["profile"],
                altitude_unit=self.graph_units.currentText(),
                speed_unit=self.graph_speed.currentText(),
            )
            self.current_profile["decoded"] = decoded
            self.profile_summary.setText(format_profile_summary(decoded))
            self.figure.clear()
            alt, speed = self.figure.subplots(2, 1, sharex=True)
            samples = decoded["samples"]
            times = [s["time_seconds"] for s in samples]
            alt.plot(
                times, [s["altitude"] for s in samples], color="#117b91", linewidth=1.8
            )
            alt.axhline(
                decoded["summary"]["deployment_altitude"],
                color="#a86b23",
                linestyle="--",
                label="Recorded deployment altitude",
            )
            alt.legend(loc="upper right")
            alt.set_ylabel("Altitude (" + decoded["altitude_unit"] + ")")
            available = [s for s in samples if s["vertical_speed"] is not None]
            speed.plot(
                [s["time_seconds"] for s in available],
                [s["vertical_speed"] for s in available],
                color="#535cac",
                linewidth=1.8,
            )
            speed.set_ylabel("Vertical speed (" + decoded["speed_unit"] + ")")
            speed.set_xlabel("Time (seconds; JumpTrack chart origin)")
            for axis in (alt, speed):
                axis.grid(alpha=0.18)
                axis.spines[["top", "right"]].set_visible(False)
            self.canvas.draw_idle()
            self._sync()
        except ValueError as exc:
            self.notice.setText(str(exc))

    def open_profile(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open saved profile", "", "Text profiles (*.txt);;All files (*)"
        )
        if path:
            try:
                raw = Path(path).read_text(encoding="utf-8")
                self._profile_loaded({"raw": raw, "profile": parse_profile(raw)})
            except (OSError, ValueError) as exc:
                self.notice.setText(str(exc))

    def export_profile(self):
        if not self.current_profile or "decoded" not in self.current_profile:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export decoded profile",
            f"jump_{self.current_profile['decoded']['jump_number']}.json",
            "JSON (*.json)",
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        self.current_profile["decoded"], indent=2, allow_nan=False
                    )
                    + "\n",
                    encoding="utf-8",
                )
                self.notice.setText("Profile exported to " + path)
            except OSError as exc:
                self.notice.setText(str(exc))

    def closeEvent(self, event):
        if self.closing_ready:
            self.bridge.stop()
            event.accept()
            return
        event.ignore()
        if self.busy:
            QMessageBox.information(
                self,
                "Operation in progress",
                "Wait for the current operation to finish before closing.",
            )
            return
        if not self._discard_for("Closing"):
            return

        def closed(_result):
            self.closing_ready = True
            self.close()

        self._submit("Closing connection…", self.bridge.session.disconnect(), closed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Synthetic local demo; no Bluetooth or hardware writes",
    )
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    configure_theme(app)
    window = MainWindow(demo=args.demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
