"""Power-off must submit once, skip EOF waiting, and tolerate shutdown cleanup."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from bleak.exc import BleakError
import jumptrack


class PowerOffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client_patch = patch.object(jumptrack, 'BleakClient')
        cls = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.client = cls.return_value
        self.client.is_connected = True
        self.client.write_gatt_char = AsyncMock()
        self.client.stop_notify = AsyncMock()
        self.client.disconnect = AsyncMock()
        self.device = jumptrack.JumpTrack(address='test-device', allow_writes=True)

    async def test_both_apis_send_once_without_waiting_for_eof(self):
        for method in ('power_off', 'preparePowerOffCommand'):
            self.client.write_gatt_char.reset_mock()
            with patch.object(asyncio, 'wait_for', side_effect=AssertionError('Must not wait for EOF')):
                result = await getattr(self.device, method)()
            self.assertEqual(result, 'Power-off command sent (no response expected).')
            self.client.write_gatt_char.assert_awaited_once_with(
                jumptrack.UART_RX, b'W-20-00000-00000-00000-00001\r', response=False)

    async def test_write_permission_still_required(self):
        self.device.allow_writes = False
        for method in ('power_off', 'preparePowerOffCommand'):
            with self.assertRaises(PermissionError):
                await getattr(self.device, method)()
        self.client.write_gatt_char.assert_not_awaited()

    async def test_ble_write_failure_is_reported(self):
        self.client.write_gatt_char.side_effect = BleakError('write failed')
        with self.assertRaisesRegex(BleakError, 'write failed'):
            await self.device.power_off()
        self.assertFalse(self.device._power_off_sent)

    async def test_shutdown_cleanup_race_is_handled_only_after_power_off(self):
        self.device._notifications_started = True
        self.client.stop_notify.side_effect = BleakError('already disconnected')
        self.client.disconnect.side_effect = BleakError('already disconnected')
        await self.device.power_off()
        await self.device.disconnect()
        self.assertFalse(self.device._notifications_started)
        self.client.disconnect.assert_awaited_once()
        self.device._power_off_sent = False
        self.client.disconnect.side_effect = None
        self.device._notifications_started = True
        with self.assertRaises(BleakError):
            await self.device.disconnect()


if __name__ == '__main__':
    unittest.main()
