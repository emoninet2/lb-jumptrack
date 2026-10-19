"""Offline golden commands transcribed from UARTCommandBuilder.java; no radio use."""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from uart_command_builder import UARTCommandBuilder

# One entry for every Java public command method/overload. Expected strings are
# literals so changes to the Python formatter cannot silently update the oracle.
CASES = [
    (
        "prepareDateTimeCommand",
        "set_datetime",
        (datetime(2026, 10, 18, 14, 7, 9),),
        {},
        "W-18-09007-00014-18010-02026",
    ),
    ("preparePowerOffCommand", "power_off", (), {}, "W-20-00000-00000-00000-00001"),
    (
        "prepareSetDistanceUOM",
        "set_distance_uom",
        ("meters",),
        {},
        "W-16-00000-00000-00000-00001",
    ),
    (
        "prepareSetSpeedUOM",
        "set_speed_uom",
        ("kmh",),
        {},
        "W-38-00000-00000-00000-00001",
    ),
    ("prepareGetSpeedUOM", "get_speed_uom", (), {}, "R-38"),
    (
        "prepareSetTotalFreeFallTimeCommand",
        "set_total_freefall_time",
        ("12", "3", "4"),
        {},
        "W-37-00012-00003-00004-00000",
    ),
    (
        "prepareSetTotalFreeFallTimeCommand",
        "set_total_freefall_time",
        (12, 3, 4),
        {},
        "W-37-00012-00003-00004-00000",
    ),
    (
        "prepareSendFlightWarningsCommand",
        "set_flight_warnings",
        ([1000, 2000, 3000],),
        {},
        "W-01-00000-01000-02000-03000",
    ),
    (
        "prepareSendFreeFallWarningsCommand",
        "set_freefall_warnings",
        (4, ["1000", "2000", "3000", "4000"]),
        {},
        "W-07-01000-02000-03000-04000",
    ),
    (
        "prepareSendFlightWarningsCommand",
        "set_flight_warnings",
        ([1000, 2000, 3000, 4000],),
        {"bank": 4},
        "W-36-01000-02000-03000-04000",
    ),
    (
        "prepareSendCanopyWarningsCommand",
        "set_canopy_warnings",
        (4, [1000, 2000, 3000]),
        {},
        "W-13-00000-01000-02000-03000",
    ),
    (
        "prepareSendFreeFallSoundSetupCommand",
        "set_sound",
        ("freefall", 7, 10),
        {},
        "W-02-00000-00000-00007-00010",
    ),
    (
        "prepareSendCanopySoundSetupCommand",
        "set_sound",
        ("canopy", 1, 1),
        {},
        "W-08-00000-00000-00001-00001",
    ),
    (
        "prepareSendFlightWarningsSoundSetupCommand",
        "set_sound",
        ("flight", 3, 8),
        {},
        "W-31-00000-00000-00003-00008",
    ),
    (
        "prepareSendFreeFallPlaySoundCommand",
        "play_sound",
        ("freefall",),
        {},
        "W-19-00000-00000-00001-00000",
    ),
    (
        "prepareSendCanopyPlaySoundCommand",
        "play_sound",
        ("canopy",),
        {},
        "W-19-00000-00000-00000-00001",
    ),
    (
        "prepareSendFlightAlarmsPlaySoundCommand",
        "play_sound",
        ("flight",),
        {},
        "W-19-00000-00001-00001-00001",
    ),
    (
        "prepareSetDefaultAlarmValuesCommand",
        "set_default_alarm_values",
        (),
        {},
        "Factory Warnings Default",
    ),
    ("prepareFactoryResetCommand", "factory_reset", (), {}, "Factory Default"),
    ("prepareReadDeviceSettingsR40Command", "get_settings_40", (), {}, "R-40"),
    ("prepareReadDeviceSettingsR41Command", "get_settings_41", (), {}, "R-41"),
    ("prepareReadDeviceSettingsR42Command", "get_settings_42", (), {}, "R-42"),
    (
        "prepareDeviceSettingsW40Command",
        "set_settings_40",
        (),
        {
            "ble_mode": "economy",
            "beeps": True,
            "dive_type": "super_slow",
            "temperature_unit": "fahrenheit",
        },
        "W-40-00001-00001-00003-00001",
    ),
    (
        "prepareWriteDeviceSettingsW41Command",
        "set_settings_41",
        (),
        {"tap_to_enable_ble": True, "flatline_cutoff": 0},
        "W-41-00000-00001-00000-00000",
    ),
    (
        "prepareDeviceSettingsW42Command",
        "set_settings_42",
        (),
        {
            "backlight_value": 75,
            "date_format": "us",
            "show_time_under_canopy": True,
            "lcd_timeout": 30,
        },
        "W-42-00001-00030-00001-00075",
    ),
    ("prepareBacklightCommand", "set_backlight", (True, 5), {}, "Backlight On 05"),
    (
        "prepareMotionAlarmCommand",
        "enable_motion_alarm",
        (5, 12),
        {},
        "Enable Motion 005 012",
    ),
    (
        "prepareSetSwoopGuideCommand",
        "set_swoop_guide",
        (True,),
        {},
        "W-21-00000-00000-00000-00001",
    ),
    (
        "prepareSetTrackGuideCommand",
        "set_track_guide",
        (False,),
        {},
        "W-21-00000-00000-00000-00000",
    ),
    (
        "prepareSetCanopyActiveBankCommand",
        "set_active_bank",
        ("canopy", 1),
        {},
        "W-23-00000-00000-00000-00001",
    ),
    (
        "prepareSetFlightWarningActiveBankCommand",
        "set_active_bank",
        ("flight", 2),
        {},
        "W-30-00000-00000-00000-00002",
    ),
    (
        "prepareSetFreeFallActiveBankCommand",
        "set_active_bank",
        ("freefall", 3),
        {},
        "W-22-00000-00000-00000-00003",
    ),
    (
        "prepareSendAltitudeCommand",
        "set_altitude",
        (65000,),
        {"negative": True},
        "W-17-00000-00000-00001-65000",
    ),
    ("prepareReadJumpCountCommand", "get_jump_counter", (), {}, "Get Jump Counter"),
    (
        "prepareSetJumpCountCommand",
        "set_jump_counter",
        (35,),
        {},
        "Set Jump Counter 00035",
    ),
    ("prepareEraseEntireLogbookCommand", "erase_logbook", (), {}, "Erase Logbook"),
    (
        "prepareGetACCCommand",
        "get_acc",
        (35, 5, 90),
        {"hex_format": False},
        "Get xACC 00035 005 090",
    ),
    (
        "prepareGetACCCommandHex",
        "get_acc",
        (35, 5, 90),
        {},
        "Get Hex xACC 00035 005 090",
    ),
    ("prepareGetDeviceInfoCommand", "get_device_info", (), {}, "Who?"),
    (
        "prepareLoadLumpProfileCommandHex",
        "get_jump_profile_hex",
        (123456,),
        {},
        "Get Hex Profile in Jump 123456",
    ),
]


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.b = UARTCommandBuilder()

    def test_all_java_overloads_have_golden_cases(self):
        from collections import Counter

        from tests.test_java_master_parity import master_methods

        self.assertEqual(
            Counter(name for name, _, _ in master_methods()),
            Counter(row[0] for row in CASES),
        )

    def test_golden_commands(self):
        for java, method, args, kwargs, expected in CASES:
            with self.subTest(java=java, args=args):
                self.assertEqual(getattr(self.b, method)(*args, **kwargs), expected)
        self.assertEqual(self.b.get_all_warnings(), "R-00")
        self.assertEqual(self.b.get_jump_list(), "Get New Jump List")

    def test_all_banks_and_warning_lengths(self):
        for method, base in [
            ("set_freefall_warnings", 3),
            ("set_canopy_warnings", 9),
            ("set_flight_warnings", 32),
        ]:
            for bank in range(1, 5):
                for values, suffix in [
                    ([1, 2, 3], "00000-00001-00002-00003"),
                    ([1, 2, 3, 4], "00001-00002-00003-00004"),
                ]:
                    args = (
                        (values,) if method == "set_flight_warnings" else (bank, values)
                    )
                    kwargs = {"bank": bank} if method == "set_flight_warnings" else {}
                    self.assertEqual(
                        getattr(self.b, method)(*args, **kwargs),
                        f"W-{base + bank:02d}-{suffix}",
                    )

    def test_enum_and_boolean_branches(self):
        self.assertEqual(
            self.b.set_distance_uom("feet"), "W-16-00000-00000-00000-00000"
        )
        self.assertEqual(self.b.set_speed_uom("mph"), "W-38-00000-00000-00000-00000")
        self.assertEqual(self.b.set_backlight(False), "Backlight Off")
        self.assertEqual(self.b.set_altitude(0), "W-17-00000-00000-00000-00000")
        for dive, code in [
            ("default", "00000"),
            ("3_seconds", "00001"),
            ("slow", "00002"),
            ("super_slow", "00003"),
        ]:
            self.assertEqual(
                self.b.set_settings_40(
                    ble_mode="automatic",
                    beeps=False,
                    dive_type=dive,
                    temperature_unit="celsius",
                ),
                f"W-40-00000-00000-{code}-00000",
            )
        self.assertEqual(
            self.b.set_settings_41(tap_to_enable_ble=False, flatline_cutoff=500),
            "W-41-00500-00000-00000-00000",
        )
        self.assertEqual(
            self.b.set_settings_42(
                backlight_value=0,
                date_format="eu",
                show_time_under_canopy=False,
                lcd_timeout=0,
            ),
            "W-42-00000-00000-00000-00000",
        )

    def test_java_null_results(self):
        invalid = [
            ("set_sound", ("freefall", 0, 1)),
            ("set_sound", ("freefall", 8, 1)),
            ("set_sound", ("flight", 1, 11)),
            ("set_sound", ("canopy", 1, 0)),
            ("set_active_bank", ("flight", 0)),
            ("set_active_bank", ("freefall", 5)),
            ("set_altitude", (65001,)),
            ("set_altitude", (-1,)),
            ("set_flight_warnings", ([1, 2],)),
            ("set_flight_warnings", (["bad", 2, 3],)),
        ]
        import logging

        with self.assertLogs("java_uart_command_builder", level=logging.ERROR):
            for method, args in invalid:
                with self.subTest(method=method, args=args):
                    self.assertIsNone(getattr(self.b, method)(*args))

    def test_java_minimum_width_and_extra_warning_rules(self):
        self.assertEqual(
            self.b.set_flight_warnings([1, 2, 3, 4, 5]), "W-01-00000-00001-00002-00003"
        )
        self.assertEqual(
            self.b.get_jump_profile_hex(1000000), "Get Hex Profile in Jump 1000000"
        )
        self.assertEqual(self.b.get_acc(1, 1000, -2), "Get Hex xACC 00001 1000 -02")
        self.assertEqual(
            self.b.set_total_freefall_time("+100000", "-2", "03"),
            "W-37-100000--0002-00003-00000",
        )

    def test_type_errors_and_wrong_uom(self):
        for method, args in [
            ("set_speed_uom", ("fps",)),
            ("get_jump_profile_hex", (True,)),
            ("get_jump_profile_hex", (2147483648,)),
            ("set_swoop_guide", (1,)),
        ]:
            with (
                self.subTest(method=method),
                self.assertRaises((TypeError, ValueError)),
            ):
                getattr(self.b, method)(*args)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import jumptrack

        self.module = jumptrack
        self.patch = patch.object(jumptrack, "BleakClient")
        self.mock = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.device = jumptrack.JumpTrack(address="test-device")

    async def test_all_wrappers_forward_commands(self):
        self.device.send_command = AsyncMock(
            return_value="W-41-00000-00000-00000-00000\nEOF\n"
        )
        for _, method, args, kwargs, expected in CASES:
            self.device.allow_writes = self.device.allow_destructive = True
            await getattr(self.device, method)(*args, **kwargs)
            self.assertEqual(self.device.send_command.call_args.args[0], expected)
        await self.device.get_acc(35, 0, 1, timeout=123)
        self.assertEqual(self.device.send_command.call_args.kwargs["timeout"], 123)
        await self.device.get_jump_profile_hex(35, timeout=124)
        self.assertEqual(self.device.send_command.call_args.kwargs["timeout"], 124)

    async def test_existing_write_guards(self):
        for method, args in [
            ("set_sound", ("canopy", 1, 1)),
            ("erase_logbook", ()),
            ("factory_reset", ()),
        ]:
            with self.assertRaises(PermissionError):
                await getattr(self.device, method)(*args)
        self.mock.return_value.write_gatt_char.assert_not_called()

    async def test_fragmented_eof_and_wire_command(self):
        async def respond(*args, **kwargs):
            for part in [b"Who?\r\nPROTRACK 3\r\nE", b"OF\r", b"\n"]:
                self.device._notification_handler(None, part)

        self.mock.return_value.write_gatt_char = AsyncMock(side_effect=respond)
        raw = await self.device.get_device_info()
        self.assertEqual(raw, "Who?\r\nPROTRACK 3\r\nEOF\r\n")
        self.mock.return_value.write_gatt_char.assert_awaited_once_with(
            self.module.UART_RX, b"Who?\r", response=False
        )

    async def test_timeout_includes_partial_response(self):
        async def respond(*args, **kwargs):
            self.device._notification_handler(None, b"incomplete")

        self.mock.return_value.write_gatt_char = AsyncMock(side_effect=respond)
        with self.assertRaisesRegex(TimeoutError, "incomplete"):
            await self.device.send_command("Who?", timeout=0.001)


class BeepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import jumptrack

        self.module = jumptrack
        with patch.object(jumptrack, "BleakClient"):
            self.device = jumptrack.JumpTrack(address="test-device", allow_writes=True)
        self.device._write = AsyncMock(return_value="EOF\r\n")

    async def test_changes_only_beeps_and_verifies(self):
        self.device.get_settings_40 = AsyncMock(
            side_effect=[
                "R-40\r\nW-40-00001-00001-00003-00001\r\nEOF\r\n",
                "R-40\r\nW-40-00001-00000-00003-00001\r\nEOF\r\n",
            ]
        )
        result = await self.device.set_button_beeps(False)
        self.assertIn("verified", result)
        self.device._write.assert_awaited_once_with("W-40-00001-00000-00003-00001")

    async def test_already_set_does_not_write(self):
        self.device.get_settings_40 = AsyncMock(
            return_value="W-40-00000-00001-00000-00000\nEOF\n"
        )
        self.assertIn("already on", await self.device.set_button_beeps(True))
        self.device._write.assert_not_awaited()

    async def test_unknown_or_incomplete_response_never_writes(self):
        for raw in [
            "EOF\n",
            "W-40-00000-00001-00000-00000",
            "W-40-00002-00001-00000-00000\nEOF\n",
            "W-40-00000-00001-00000-00000\nW-40-00000-00001-00000-00000\nEOF\n",
        ]:
            self.device.get_settings_40 = AsyncMock(return_value=raw)
            with self.assertRaises(ValueError):
                await self.device.set_button_beeps(False)
        self.device._write.assert_not_awaited()

    async def test_verification_mismatch(self):
        self.device.get_settings_40 = AsyncMock(
            return_value="W-40-00000-00001-00000-00000\nEOF\n"
        )
        with self.assertRaisesRegex(RuntimeError, "verification mismatch"):
            await self.device.set_button_beeps(False)

    async def test_write_timeout_is_not_retried(self):
        self.device.get_settings_40 = AsyncMock(
            return_value="W-40-00000-00001-00000-00000\nEOF\n"
        )
        self.device._write.side_effect = TimeoutError("missing EOF")
        with self.assertRaisesRegex(TimeoutError, "may have applied"):
            await self.device.set_button_beeps(False)
        self.device._write.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
