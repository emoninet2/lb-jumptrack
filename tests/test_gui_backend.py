"""Desktop staging, apply verification and destructive guards without hardware."""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from gui_backend import Draft
from gui_demo import DemoSession


class DesktopSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_numeric_flatline_readonly_clear_and_tap_preservation(self):
        self.device.groups[41][0] = 500
        snapshot = await self.session.read_snapshot()
        draft = Draft(snapshot)
        with self.assertRaises(ValueError):
            draft.set("settings.41.0", 600)
        result = await self.session.apply(snapshot, {"settings.41.1": 0})
        self.assertFalse(result.error)
        self.assertEqual(result.snapshot.values["settings.41.0"], 500)
        result = await self.session.apply(result.snapshot, {"settings.41.0": 0})
        self.assertFalse(result.error)
        self.assertEqual(result.snapshot.values["settings.41.0"], 0)
        self.assertTrue(self.session.connected)

    async def test_guide_staged_apply_readback_and_missing_status(self):
        from jumptrack import format_warning_configuration, parse_warning_configuration

        key = "warnings.canopy.guide"
        draft = Draft(self.snapshot)
        draft.set(key, 1)
        self.assertEqual(self.device.guide, 0)
        result = await self.session.apply(self.snapshot, draft.pending)
        self.assertFalse(result.error)
        self.assertIn(key, result.verified)
        self.assertEqual(result.snapshot.values[key], 1)
        self.assertTrue(self.session.connected)
        draft.reconcile(result.snapshot)
        self.assertFalse(draft.pending)
        result = await self.session.apply(result.snapshot, {key: 0})
        self.assertFalse(result.error)
        self.assertEqual(result.snapshot.values[key], 0)
        raw = await self.device.get_all_warnings()
        config = parse_warning_configuration(raw)
        self.assertIn("Canopy guide: off", format_warning_configuration(config))
        for replacement in ("", "W-21-00000-00000-00000-00002"):
            config = parse_warning_configuration(
                raw.replace("W-21-00000-00000-00000-00000", replacement)
            )
            self.assertIsNone(config["guide_enabled"])

    async def test_sound_playback_only_uses_play_command_and_retains_connection(self):
        self.device.play_sound = AsyncMock(wraps=self.device.play_sound)
        self.device.set_sound = AsyncMock(wraps=self.device.set_sound)
        for category in ("flight", "freefall", "canopy"):
            await self.session.test_sound(self.snapshot, category)
            self.device.play_sound.assert_awaited_with(
                category, wait_for_response=False
            )
            self.assertTrue(self.session.connected)
            self.assertFalse(self.device.allow_writes)
        self.device.set_sound.assert_not_awaited()
        with self.assertRaises(ValueError):
            await self.session.test_sound(self.snapshot, "unknown")
        self.assertEqual(self.device.play_sound.await_count, 3)

    async def test_sound_failure_resets_permission_without_retry(self):
        self.device.play_sound = AsyncMock(
            side_effect=TimeoutError("sound submission failed")
        )
        with self.assertRaises(TimeoutError):
            await self.session.test_sound(self.snapshot, "freefall")
        self.device.play_sound.assert_awaited_once()
        self.assertFalse(self.device.allow_writes)
        self.assertTrue(self.session.connected)

    async def test_sound_reserves_the_apk_playback_window(self):
        self.session.sound_playback_seconds = 25
        with patch("gui_backend.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await self.session.test_sound(self.snapshot, "flight")
        sleep.assert_awaited_once_with(25)
        self.assertTrue(self.session.connected)

    async def test_clock_write_readback_and_offset_one_shot_disconnect(self):
        value = datetime(2026, 10, 19, 13, 42, 23)
        snapshot = await self.session.set_clock(self.snapshot, value)
        self.assertEqual(snapshot.details["datetime"], value.isoformat())
        self.assertTrue(self.session.connected)
        self.assertFalse(self.device.allow_writes)
        self.device.set_altitude = AsyncMock(wraps=self.device.set_altitude)
        for phrase, offset in [("SET", 500), ("SET OFFSET", 10000)]:
            with self.assertRaises(ValueError):
                await self.session.set_offset(snapshot, offset, phrase)
        self.device.set_altitude.assert_not_awaited()
        await self.session.set_offset(snapshot, -500, "SET OFFSET")
        self.device.set_altitude.assert_awaited_once_with(
            500, negative=True, wait_for_response=False
        )
        self.assertFalse(self.session.connected)
        self.assertFalse(self.device.allow_writes)
        loaded = await self.session.connect("DEMO-LOCAL")
        self.assertEqual(loaded.details["altitude_offset"], -500)

    async def test_offset_blocks_changed_units_and_clock_requires_readback(self):
        self.device.distance = 1
        self.device.set_altitude = AsyncMock(wraps=self.device.set_altitude)
        with self.assertRaisesRegex(ValueError, "units changed"):
            await self.session.set_offset(self.snapshot, 200, "SET OFFSET")
        self.device.set_altitude.assert_not_awaited()
        self.device.set_datetime = AsyncMock()
        with self.assertRaisesRegex(ValueError, "not verified"):
            await self.session.set_clock(self.snapshot, datetime(2026, 10, 19, 12, 0))
        self.assertTrue(self.session.connected)
        self.assertFalse(self.device.allow_writes)

    async def asyncSetUp(self):
        self.session = DemoSession()
        self.snapshot = await self.session.connect("DEMO-LOCAL")
        self.device = self.session.device
        self.draft = Draft(self.snapshot)

    async def asyncTearDown(self):
        await self.session.disconnect()

    async def test_edits_never_write_and_group_apply_preserves_fields(self):
        self.device.set_settings_40 = AsyncMock(wraps=self.device.set_settings_40)
        self.draft.set("settings.40.1", 1)
        self.draft.set("settings.40.2", 2)
        self.device.set_settings_40.assert_not_awaited()
        self.assertEqual(self.device.groups[40], [0, 0, 0, 0])
        result = await self.session.apply(self.draft.snapshot, self.draft.pending)
        self.assertFalse(result.error)
        self.device.set_settings_40.assert_awaited_once()
        self.assertEqual(self.device.groups[40], [0, 1, 2, 0])
        self.assertFalse(self.device.allow_writes)
        self.draft.reconcile(result.snapshot)
        self.assertEqual(self.draft.pending, {})

    async def test_discard_and_revert_clear_changes_without_writes(self):
        self.draft.set("settings.40.1", 1)
        self.draft.set("settings.40.1", 0)
        self.assertEqual(self.draft.pending, {})
        self.draft.set("settings.40.2", 1)
        self.draft.discard()
        self.assertEqual(self.draft.pending, {})
        self.assertEqual(self.device.groups[40], [0, 0, 0, 0])

    async def test_repeated_applies_stay_connected_without_logbook_downloads(self):
        self.device.get_jump_list = AsyncMock(
            side_effect=AssertionError("Unexpected logbook read")
        )
        key = "warnings.freefall.bank.1"
        for value in ((6000, 5000, 4000, 2500), (6500, 5000, 4000, 2500)):
            result = await self.session.apply(self.snapshot, {key: value})
            self.assertFalse(result.error)
            self.assertTrue(self.session.connected)
            self.assertEqual(result.snapshot.values[key], value)
            self.snapshot = result.snapshot
        self.device.get_jump_list.assert_not_awaited()

    async def test_external_changes_block_write_and_preserve_requested_edit(self):
        self.draft.set("settings.40.2", 2)
        self.device.groups[40][2] = 1
        self.device.set_settings_40 = AsyncMock(wraps=self.device.set_settings_40)
        result = await self.session.apply(self.snapshot, self.draft.pending)
        self.assertIn("changed since", result.error)
        self.device.set_settings_40.assert_not_awaited()
        self.draft.reconcile(result.snapshot)
        self.assertEqual(self.draft.value("settings.40.2"), 2)
        self.assertEqual(self.draft.snapshot.values["settings.40.2"], 1)

    async def test_partial_failure_keeps_unverified_changes_and_does_not_retry(self):
        self.draft.set("settings.40.1", 1)
        key = "warnings.freefall.bank.1"
        self.draft.set(key, (6000, 5000, 4000, 2500))
        self.device.set_freefall_warnings = AsyncMock(
            side_effect=TimeoutError("response lost")
        )
        result = await self.session.apply(self.snapshot, self.draft.pending)
        self.assertTrue(result.connected)
        self.assertTrue(self.session.connected)
        self.assertIn("may have applied", result.error)
        self.device.set_freefall_warnings.assert_awaited_once()
        self.assertFalse(self.device.allow_writes)
        self.draft.reconcile(result.snapshot)
        self.assertNotIn("settings.40.1", self.draft.pending)
        self.assertIn(key, self.draft.pending)
        with self.assertRaisesRegex(ValueError, "Reload device values"):
            await self.session.apply(self.snapshot, {key: (6000, 5000, 4000, 2500)})
        self.device.set_freefall_warnings.assert_awaited_once()
        await self.session.read_snapshot()
        self.assertFalse(self.session.needs_reload)

    async def test_failed_readback_preserves_connection_and_stops_writes(self):
        original = self.device.get_all_warnings
        self.device.get_all_warnings = AsyncMock(
            side_effect=[await original(), TimeoutError("readback failed")]
        )
        result = await self.session.apply(
            self.snapshot, {"warnings.freefall.bank.1": (6000, 5000, 4000, 2500)}
        )
        self.assertIn("readback failed", result.error)
        self.assertTrue(self.session.connected)
        self.assertTrue(result.connected)
        self.assertTrue(self.session.needs_reload)
        self.assertEqual(self.device.banks["freefall"][1], (6000, 5000, 4000, 2500))

    async def test_mismatched_readback_stops_remaining_operations(self):
        self.draft.set("settings.40.1", 1)
        self.draft.set("warnings.flight.active_bank", 2)
        self.device.set_settings_40 = AsyncMock()  # Acknowledged but not changed.
        self.device.set_active_bank = AsyncMock(wraps=self.device.set_active_bank)
        result = await self.session.apply(self.snapshot, self.draft.pending)
        self.assertIn("Readback did not match", result.error)
        self.device.set_active_bank.assert_not_awaited()
        self.assertFalse(self.device.allow_writes)

    async def test_warning_banks_sound_and_active_bank_readback(self):
        self.draft.set("warnings.flight.bank.2", (0, 9000, 1500, 1000))
        self.draft.set("warnings.canopy.pitch", 3)
        self.draft.set("warnings.freefall.active_bank", 2)
        result = await self.session.apply(self.snapshot, self.draft.pending)
        self.assertFalse(result.error)
        self.assertEqual(
            result.snapshot.values["warnings.flight.bank.2"], (0, 9000, 1500, 1000)
        )
        self.assertEqual(result.snapshot.values["warnings.canopy.volume"], 7)
        self.assertEqual(result.snapshot.values["warnings.freefall.active_bank"], 2)

    async def test_units_and_warning_changes_must_be_separate(self):
        self.draft.set("distance_unit", 1)
        self.draft.set("warnings.flight.bank.1", (0, 8000, 1500, 1000))
        with self.assertRaisesRegex(ValueError, "separately"):
            await self.session.apply(self.snapshot, self.draft.pending)
        self.assertEqual(self.device.distance, 0)

    async def test_destructive_confirmation_and_address_are_required(self):
        self.device.erase_logbook = AsyncMock(wraps=self.device.erase_logbook)
        for phrase, address in [("ERASE", "DEMO-LOCAL"), ("ERASE LOGBOOK", "OTHER")]:
            with self.assertRaises(ValueError):
                await self.session.destructive("erase-logbook", phrase, address)
        self.device.erase_logbook.assert_not_awaited()
        self.assertEqual(len(self.device.jumps), 3)
        await self.session.destructive("erase-logbook", "ERASE LOGBOOK", "DEMO-LOCAL")
        self.assertEqual(self.device.jumps, [])
        self.assertFalse(self.device.allow_destructive)
        self.assertFalse(self.session.connected)
        with self.assertRaises(ConnectionError):
            await self.session.destructive(
                "erase-logbook", "ERASE LOGBOOK", "DEMO-LOCAL"
            )
        self.device.erase_logbook.assert_awaited_once()

    async def test_missing_or_different_device_settings_cannot_be_applied(self):
        with self.assertRaises(ValueError):
            self.draft.set("settings.41.3", 1)
        with self.assertRaises(ValueError):
            self.draft.set("warnings.flight.active_bank", 5)
        self.draft.set("settings.40.1", 1)
        await self.session.connect("OTHER")
        with self.assertRaisesRegex(ValueError, "different device"):
            await self.session.apply(self.snapshot, self.draft.pending)

    async def test_profile_is_decoded_and_integrity_checked(self):
        from profile_decoder import decode_profile

        result = await self.session.profile(35)
        decoded = decode_profile(result["profile"])
        self.assertTrue(decoded["checksum_verified"])
        self.assertEqual(decoded["summary"]["deployment_altitude"], 3400)
        self.assertEqual(len(decoded["samples"]), 1000)
        self.assertFalse(self.device.allow_writes)

    async def test_external_unit_change_blocks_bank_edit(self):
        self.draft.set("warnings.freefall.bank.1", (6000, 5000, 4000, 2500))
        self.device.distance = 1
        self.device.set_freefall_warnings = AsyncMock(
            wraps=self.device.set_freefall_warnings
        )
        result = await self.session.apply(self.snapshot, self.draft.pending)
        self.assertIn("units changed", result.error)
        self.device.set_freefall_warnings.assert_not_awaited()

    async def test_demo_deletion_persists_after_reconnect(self):
        await self.session.destructive("erase-logbook", "ERASE LOGBOOK", "DEMO-LOCAL")
        snapshot = await self.session.connect("DEMO-LOCAL")
        self.assertEqual(snapshot.jumps, [])

    async def test_uncertain_destructive_result_disconnects_without_retry(self):
        self.device.factory_reset = AsyncMock(side_effect=TimeoutError("no response"))
        with self.assertRaisesRegex(RuntimeError, "may have applied"):
            await self.session.destructive(
                "factory-reset", "FACTORY RESET", "DEMO-LOCAL"
            )
        self.device.factory_reset.assert_awaited_once()
        self.assertFalse(self.device.allow_destructive)
        self.assertFalse(self.session.connected)
