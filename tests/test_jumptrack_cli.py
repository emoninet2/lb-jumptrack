"""CLI coverage tests: no real Bluetooth clients are constructed."""

import contextlib
import io
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jumptrack
from jumptrack_cli import operation, preview
from uart_command_builder import UARTCommandBuilder

# CLI equivalents for each Java-signature golden test, in the same order.
GOLDEN_CLI = [
    "set-datetime 2026-10-18T14:07:09",
    "power-off",
    "set-distance-unit meters",
    "set-speed-unit kmh",
    "speed-unit",
    "set-freefall-time 12 3 4",
    "set-freefall-time 12 3 4",
    "set-warnings flight 1000 2000 3000",
    "set-warnings freefall 1000 2000 3000 4000 --bank 4",
    "set-warnings flight 1000 2000 3000 4000 --bank 4",
    "set-warnings canopy 1000 2000 3000 --bank 4",
    "set-sound freefall 7 10",
    "set-sound canopy 1 1",
    "set-sound flight 3 8",
    "play-sound freefall",
    "play-sound canopy",
    "play-sound flight",
    "default-alarms",
    "factory-reset",
    "settings-40",
    "settings-41",
    "settings-42",
    "set-settings-40 --ble-mode economy --beeps on --dive-type super_slow --temperature-unit fahrenheit",
    "set-settings-41 --tap-to-enable-ble on --flatline-cutoff 0",
    "set-settings-42 --backlight-value 75 --date-format us --show-time-under-canopy on --lcd-timeout 30",
    "backlight on --value 5",
    "motion-alarm 5 12",
    "swoop-guide on",
    "track-guide off",
    "set-active-bank canopy 1",
    "set-active-bank flight 2",
    "set-active-bank freefall 3",
    "set-altitude 65000 --negative",
    "jump-counter",
    "set-jump-counter 35",
    "erase-logbook",
    "acc 35 5 90 --format text",
    "acc 35 5 90",
    "info",
    "profile 123456",
]


class CLITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.parser = jumptrack.build_parser()

    def test_cli_matches_all_java_golden_commands(self):
        from tests.test_uart_command_builder import CASES

        self.assertEqual(len(CASES), len(GOLDEN_CLI))
        methods = set()
        for cli, row in zip(GOLDEN_CLI, CASES):
            with self.subTest(cli=cli):
                op = operation(self.parser.parse_args(shlex.split(cli)))
                self.assertEqual(preview(op, UARTCommandBuilder()), row[4])
                self.assertEqual(op.method, row[1])
                methods.add(op.method)
        for cli, expected in [("warnings", "R-00"), ("jump-list", "Get New Jump List")]:
            op = operation(self.parser.parse_args([cli]))
            self.assertEqual(preview(op, UARTCommandBuilder()), expected)
            methods.add(op.method)
        public = {
            name
            for name, value in vars(UARTCommandBuilder).items()
            if not name.startswith("_")
            and callable(value)
            and not isinstance(value, type)
        }
        self.assertEqual(methods, public)

    async def test_every_command_dry_run_never_constructs_ble_client(self):
        with (
            patch.object(jumptrack, "BleakClient") as client,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for cli in GOLDEN_CLI + [
                "warnings",
                "jump-list",
                "beeps off",
                "backlight off",
            ]:
                await jumptrack.main(["--dry-run", *shlex.split(cli)])
            client.assert_not_called()

    async def test_destructive_operations_require_flag_before_connecting(self):
        for cli in ["erase-logbook", "factory-reset", "set-jump-counter 12"]:
            with (
                self.subTest(cli=cli),
                patch.object(jumptrack, "BleakClient") as client,
            ):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as exc,
                ):
                    await jumptrack.main(shlex.split(cli))
                self.assertEqual(exc.exception.code, 2)
                client.assert_not_called()
        with patch.object(jumptrack, "run_operation", new_callable=AsyncMock) as run:
            await jumptrack.main(
                ["--address", "test-device", "--allow-destructive", "erase-logbook"]
            )
            self.assertTrue(run.call_args.args[1].destructive)

    async def test_invalid_inputs_fail_before_connecting(self):
        invalid = [
            "set-warnings freefall 1 2 3",
            "set-warnings flight 1 2",
            "set-sound flight 8 1",
            "set-altitude 65001",
            "set-active-bank canopy 5",
            "set-settings-40 --beeps off",
            "set-datetime invalid",
            "set-datetime 2026-10-18T14:00:00+02:00",
            "--beeps off info",
            "--dry-run --beeps off",
            "--settings info",
        ]
        for cli in invalid:
            with (
                self.subTest(cli=cli),
                patch.object(jumptrack, "BleakClient") as client,
            ):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as exc,
                ):
                    await jumptrack.main(shlex.split(cli))
                self.assertEqual(exc.exception.code, 2)
                client.assert_not_called()

    async def test_live_dispatch_permissions_and_output_with_mock(self):
        for cli, method, write in [
            ("info", "get_device_info", False),
            ("beeps off", "set_button_beeps", True),
            ("set-sound canopy 1 2", "set_sound", True),
        ]:
            with (
                tempfile.TemporaryDirectory() as temp,
                patch.object(jumptrack, "JumpTrack") as cls,
            ):
                dev = cls.return_value
                dev.connect = AsyncMock()
                dev.disconnect = AsyncMock()
                setattr(dev, method, AsyncMock(return_value="test response"))
                out = Path(temp) / "result.txt"
                with contextlib.redirect_stdout(io.StringIO()):
                    await jumptrack.main(
                        [
                            "--address",
                            "test-device",
                            "--output",
                            str(out),
                            *shlex.split(cli),
                        ]
                    )
                self.assertEqual(out.read_text(), "test response")
                self.assertEqual(cls.call_args.kwargs["allow_writes"], write)
                self.assertFalse(cls.call_args.kwargs["allow_destructive"])
                getattr(dev, method).assert_awaited_once()
                dev.disconnect.assert_awaited_once()

    async def test_timeout_returns_failure_and_disconnects(self):
        with patch.object(jumptrack, "JumpTrack") as cls:
            dev = cls.return_value
            dev.connect = AsyncMock()
            dev.disconnect = AsyncMock()
            dev.get_device_info = AsyncMock(side_effect=TimeoutError("no EOF"))
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as exc,
            ):
                await jumptrack.main(["--address", "test-device", "info"])
            self.assertEqual(exc.exception.code, 1)
            dev.disconnect.assert_awaited_once()

    async def test_legacy_beep_flag(self):
        with patch.object(jumptrack, "JumpTrack") as cls:
            dev = cls.return_value
            dev.connect = AsyncMock()
            dev.disconnect = AsyncMock()
            dev.set_button_beeps = AsyncMock(return_value="off")
            with contextlib.redirect_stdout(io.StringIO()):
                await jumptrack.main(["--address", "test-device", "--beeps", "off"])
            dev.set_button_beeps.assert_awaited_once_with(False)
            self.assertTrue(cls.call_args.kwargs["allow_writes"])


if __name__ == "__main__":
    unittest.main()
