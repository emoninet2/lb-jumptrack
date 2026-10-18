"""Grouped routing and settings preservation, without Bluetooth hardware."""

import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

import jumptrack
from jumptrack_cli import command_tree, operation


class GroupedCLI(unittest.IsolatedAsyncioTestCase):
    def test_grouped_routes_match_existing_operations(self):
        parser = jumptrack.build_parser()
        pairs = [
            ("device info", "info"),
            ("logbook list", "jump-list"),
            ("logbook totals jumps set 35", "set-jump-counter 35"),
            ("logbook totals freefall-time set 1 2 3", "set-freefall-time 1 2 3"),
            ("settings beeps off", "beeps off"),
            ("alarms sound canopy set 1 2", "set-sound canopy 1 2"),
            ("alarms sound flight play", "play-sound flight"),
            (
                "alarms warnings freefall set 1000 2000 3000 --bank 1",
                "set-warnings freefall 1000 2000 3000 --bank 1",
            ),
            ("alarms warnings canopy select-bank 2", "set-active-bank canopy 2"),
            (
                "advanced java prepareGetDeviceInfoCommand",
                "java prepareGetDeviceInfoCommand",
            ),
        ]
        for grouped, legacy in pairs:
            with self.subTest(grouped=grouped):
                self.assertEqual(
                    operation(parser.parse_args(grouped.split())),
                    operation(parser.parse_args(legacy.split())),
                )
        tree = command_tree(parser)
        self.assertIn("│   ├── beeps", tree)
        self.assertNotIn("├── set-settings-40", tree)

    async def test_offline_paths_and_unknown_commands_never_connect(self):
        for argv in [
            ["tree"],
            ["device", "list-models"],
            ["settings"],
            ["advanced", "constants"],
        ]:
            with (
                patch.object(jumptrack, "BleakClient") as client,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                await jumptrack.main(argv)
                client.assert_not_called()
        with (
            patch.object(jumptrack, "BleakClient") as client,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as exc:
                await jumptrack.main(["settings", "airspeed", "sas"])
            self.assertEqual(exc.exception.code, 2)
            client.assert_not_called()

    async def test_field_updates_preserve_other_fields_and_verify(self):
        cases = [
            (40, 3, 1, "00001-00000-00002-00000", "00001-00000-00002-00001"),
            (41, 1, 1, "00001-00000-00000-00000", "00001-00001-00000-00000"),
            (42, 2, 1, "00001-00030-00000-00075", "00001-00030-00001-00075"),
        ]
        for group, index, value, before, after in cases:
            dev = jumptrack.JumpTrack(address="test", allow_writes=True)
            setattr(
                dev,
                f"get_settings_{group}",
                AsyncMock(
                    side_effect=[
                        f"W-{group}-{before}\r\nEOF\r\n",
                        f"W-{group}-{after}\r\nEOF\r\n",
                    ]
                ),
            )
            dev._write = AsyncMock()
            await dev.set_setting_field(group, index, value)
            dev._write.assert_awaited_once_with(f"W-{group}-{after}")

    async def test_bad_response_prevents_write_and_mismatch_fails(self):
        dev = jumptrack.JumpTrack(address="test", allow_writes=True)
        dev.get_settings_41 = AsyncMock(return_value="unknown\r\nEOF\r\n")
        dev._write = AsyncMock()
        with self.assertRaises(ValueError):
            await dev.set_setting_field(41, 0, 1)
        dev._write.assert_not_called()
        dev.get_settings_41 = AsyncMock(
            return_value="W-41-00000-00000-00000-00000\r\nEOF\r\n"
        )
        with self.assertRaises(RuntimeError):
            await dev.set_setting_field(41, 0, 1)

    async def test_grouped_destructive_gate(self):
        with (
            patch.object(jumptrack, "BleakClient") as client,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                await jumptrack.main(["logbook", "totals", "jumps", "set", "35"])
            client.assert_not_called()

    async def test_dive_type_read_decodes_without_write(self):
        parser = jumptrack.build_parser()
        op = operation(parser.parse_args(["settings", "dive-type"]))
        self.assertEqual(op.method, "get_dive_type")
        self.assertFalse(op.write)
        dev = jumptrack.JumpTrack(address="test")
        dev.get_settings_40 = AsyncMock(
            return_value="W-40-00000-00001-00002-00000\r\nEOF\r\n"
        )
        dev._write = AsyncMock()
        self.assertIn("slow (SLOW) (code 2)", await dev.get_dive_type())
        dev._write.assert_not_called()

    def test_settings_summary_decodes_known_values_and_keeps_unknowns(self):
        raw = (
            "W-38-00000-00000-00000-00001\r\nEOF\r\n"
            "W-40-00001-00000-00001-00000\r\nEOF\r\n"
            "W-41-00000-00001-00000-00000\r\nEOF\r\n"
            "W-42-00000-00030-00001-00075\r\nEOF\r\n"
        )
        summary = jumptrack.format_settings(raw)
        for text in [
            "Speed units: kmh",
            "Dive type: 3-sec",
            "Button beeps: off",
            "Tap to enable BLE: on",
            "Show time under canopy: on",
            raw,
        ]:
            self.assertIn(text, summary)
        self.assertIn(
            "Dive type: unknown (code 9)",
            jumptrack.format_settings(
                raw.replace("00001-00000-00001-00000", "00001-00000-00009-00000")
            ),
        )
        self.assertIn("unrecognized layout", jumptrack.format_settings("W-40-00000\n"))

    def test_global_help_contains_only_shared_options(self):
        parser = jumptrack.build_parser()
        help_text = parser.format_help()
        for flag in (
            "--beeps",
            "--settings",
            "--profile",
            "--warnings",
            "--list-devices",
        ):
            self.assertNotIn(flag, help_text)
        for flag in (
            "--address",
            "--debug",
            "--output",
            "--dry-run",
            "--allow-destructive",
        ):
            self.assertIn(flag, help_text)
        self.assertNotIn("airspeed", command_tree(parser))
