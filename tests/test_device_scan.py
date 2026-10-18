"""Discovery filters and CLI behavior without a Bluetooth adapter."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bleak.exc import BleakError

import jumptrack


def advertisement(name, address, rssi, local_name=None):
    return (
        SimpleNamespace(name=name, address=address),
        SimpleNamespace(local_name=local_name, rssi=rssi),
    )


class DeviceScanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.results = {
            "a": advertisement("PROTRACK 3", "AA:01", -60),
            "b": advertisement("Headphones", "BB:02", -20),
            "c": advertisement(None, "CC:03", None),
            "d": advertisement("cached name", "DD:04", -40, "STELLA"),
        }

    async def test_default_filter_and_signal_order(self):
        with patch.object(
            jumptrack.BleakScanner,
            "discover",
            new_callable=AsyncMock,
            return_value=self.results,
        ) as discover:
            rows = await jumptrack.scan_devices(timeout=3)
        discover.assert_awaited_once_with(timeout=3, return_adv=True)
        self.assertEqual([r["name"] for r in rows], ["STELLA", "PROTRACK 3"])
        self.assertTrue(rows[1]["verified_model"])
        self.assertFalse(rows[0]["verified_model"])

    async def test_name_address_and_all_filters(self):
        with patch.object(
            jumptrack.BleakScanner,
            "discover",
            new_callable=AsyncMock,
            return_value=self.results,
        ):
            self.assertEqual(len(await jumptrack.scan_devices(all_devices=True)), 4)
            self.assertEqual(
                (await jumptrack.scan_devices(query=" protrack "))[0]["address"],
                "AA:01",
            )
            self.assertEqual(
                (await jumptrack.scan_devices(all_devices=True, query="bb:"))[0][
                    "name"
                ],
                "Headphones",
            )
            self.assertEqual(await jumptrack.scan_devices(query="Headphones"), [])
            unnamed = await jumptrack.scan_devices(all_devices=True, query="CC:03")
            self.assertIn("unknown", jumptrack.format_scan_results(unnamed))

    async def test_json_output_and_file_without_client_or_address(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "devices.json"
            stdout = io.StringIO()
            with (
                patch.object(
                    jumptrack.BleakScanner,
                    "discover",
                    new_callable=AsyncMock,
                    return_value=self.results,
                ),
                patch.object(jumptrack, "BleakClient") as client,
                contextlib.redirect_stdout(stdout),
            ):
                await jumptrack.main(
                    ["--output", str(output), "device", "scan", "--all", "--json"]
                )
            self.assertEqual(
                json.loads(output.read_text()), json.loads(stdout.getvalue())
            )
            self.assertEqual(len(json.loads(stdout.getvalue())), 4)
            client.assert_not_called()

    async def test_dry_run_and_invalid_options_do_not_scan(self):
        with patch.object(
            jumptrack.BleakScanner, "discover", new_callable=AsyncMock
        ) as discover:
            with contextlib.redirect_stdout(io.StringIO()):
                await jumptrack.main(["--dry-run", "device", "scan"])
            for args in [
                ["device", "scan", "--timeout", "0"],
                ["device", "scan", "--timeout", "301"],
                ["--beeps", "off", "device", "scan"],
                ["--allow-destructive", "device", "scan"],
            ]:
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as exc,
                ):
                    await jumptrack.main(args)
                self.assertEqual(exc.exception.code, 2)
            discover.assert_not_awaited()

    async def test_adapter_error_is_reported_without_traceback(self):
        with patch.object(
            jumptrack.BleakScanner,
            "discover",
            new_callable=AsyncMock,
            side_effect=BleakError("adapter unavailable"),
        ):
            stderr = io.StringIO()
            with (
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as exc,
            ):
                await jumptrack.main(["device", "scan"])
            self.assertEqual(exc.exception.code, 1)
            self.assertIn("adapter unavailable", stderr.getvalue())

    async def test_empty_results(self):
        with patch.object(
            jumptrack.BleakScanner, "discover", new_callable=AsyncMock, return_value={}
        ):
            rows = await jumptrack.scan_devices()
        self.assertEqual(rows, [])
        self.assertIn("No matching", jumptrack.format_scan_results(rows))
