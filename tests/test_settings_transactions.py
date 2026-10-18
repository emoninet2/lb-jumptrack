"""Regression checks for serialized, conservative settings updates."""

import asyncio
import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

import jumptrack
from java_uart_command_builder import (
    DeviceBLEMode,
    DeviceDiveType,
    DeviceTemperatureUnits,
)


class SettingsTransactions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.object(jumptrack, "BleakClient"):
            self.device = jumptrack.JumpTrack(address="test", allow_writes=True)
        self.device._write = AsyncMock()

    async def test_concurrent_updates_preserve_both_changes(self):
        state = [0, 0, 0, 0]

        async def read():
            snapshot = list(state)
            await asyncio.sleep(0)
            return "W-40-" + "-".join(f"{v:05d}" for v in snapshot) + "\r\nEOF\r\n"

        async def write(command):
            await asyncio.sleep(0)
            state[:] = [int(v) for v in command.split("-")[2:]]

        self.device.get_settings_40 = AsyncMock(side_effect=read)
        self.device._write.side_effect = write
        await asyncio.gather(
            self.device.set_setting_field(40, 0, 1),
            self.device.set_setting_field(40, 3, 1),
        )
        self.assertEqual(state, [1, 0, 0, 1])

    async def test_noop_and_invalid_fields_never_write(self):
        self.device.get_settings_40 = AsyncMock(
            return_value="W-40-00000-00000-00000-00000\nEOF\n"
        )
        await self.device.set_setting_field(40, 2, 0)
        for group, index, value in [
            (40, 2, True),
            (40, -1, 0),
            (41, 2, 1),
            (42, 1, -1),
            (40, 0, 2),
        ]:
            with (
                self.subTest(group=group, index=index, value=value),
                self.assertRaises(ValueError),
            ):
                await self.device.set_setting_field(group, index, value)
        self.device._write.assert_not_awaited()

    async def test_reserved_duplicate_and_incomplete_records_never_write(self):
        for raw in [
            "W-41-00000-00000-00001-00000\nEOF\n",
            "W-41-00000-00000-00000-00000\nNOTEOF\n",
            "W-41-00000-00000-00000-00000\nEOF\ntrailing",
            ("W-41-00000-00000-00000-00000\n" * 2) + "EOF\n",
        ]:
            self.device.get_settings_41 = AsyncMock(return_value=raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                await self.device.set_setting_field(41, 0, 1)
        self.device._write.assert_not_awaited()

    async def test_complete_group_java_writes_use_transaction_lock(self):
        self.device.send_command = AsyncMock(return_value="EOF\r\n")
        async with self.device.settings_lock:
            task = asyncio.create_task(
                self.device.prepareDeviceSettingsW40Command(
                    DeviceBLEMode.AUTOMATIC,
                    False,
                    DeviceDiveType.DEFAULT,
                    DeviceTemperatureUnits.CELSIUS,
                )
            )
            await asyncio.sleep(0)
            self.device.send_command.assert_not_awaited()
        await task
        self.device.send_command.assert_awaited_once()

    async def test_missing_address_fails_before_client_creation(self):
        with (
            patch.object(jumptrack, "ADDRESS", None),
            patch.object(jumptrack, "BleakClient") as client,
        ):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as exc,
            ):
                await jumptrack.main(["device", "info"])
            self.assertEqual(exc.exception.code, 2)
            client.assert_not_called()

    def test_eof_must_be_a_complete_line(self):
        self.device._notification_handler(None, b"NOTEOF\r\n")
        self.assertFalse(self.device.response_event.is_set())
        self.device._notification_handler(None, b"EOF\r")
        self.assertFalse(self.device.response_event.is_set())
        self.device._notification_handler(None, b"\n")
        self.assertTrue(self.device.response_event.is_set())

    def test_invalid_jump_date_does_not_discard_valid_rows(self):
        rows = jumptrack.parse_jump_list(
            "35,2026,99,27,17,38,1217,15360\n36,2026,9,27,17,38,1217,15360"
        )
        self.assertEqual([row["jump_number"] for row in rows], [36])
