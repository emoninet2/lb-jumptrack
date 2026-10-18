"""CRC vectors, corruption handling and ACK compatibility without hardware."""

import binascii
import unittest
from unittest.mock import AsyncMock, patch

import jumptrack
from tests.test_profile_parser import reply
from wire_protocol import verify_response


class WireIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def test_standard_vector_and_captured_empty_register_response(self):
        self.assertEqual(binascii.crc_hqx(b"123456789", 0), 0x31C3)
        raw = "R-07\r\nCheckSum.Bytes: 00006\r\nCheckSum.Sum: 27088\r\nEOF\r\n"
        self.assertTrue(verify_response(raw)["verified"])
        self.assertTrue(verify_response("\n" + raw.replace("\r\n", "\n"))["verified"])

    def test_corruption_bad_length_ambiguity_and_truncation_rejected(self):
        raw = reply()
        for invalid in [
            raw.replace("13760", "13761"),
            raw.replace("EOF", ""),
            raw.replace("CheckSum.Bytes:", "CheckSum.Bad:"),
            raw + "CheckSum.Sum: 00000\n",
            raw.replace("CheckSum.Sum:", "CheckSum.Sum: x"),
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                verify_response(invalid, required=True)
        self.assertFalse(verify_response("ACK\r\nEOF\r\n")["verified"])
        with self.assertRaises(ValueError):
            verify_response("ACK\r\nEOF\r\n", required=True)

    async def test_live_corruption_fails_without_retry(self):
        with patch.object(jumptrack, "BleakClient") as cls:
            device = jumptrack.JumpTrack(address="test")
            client = cls.return_value
        client.is_connected = True

        async def respond(*_args, **_kwargs):
            device._notification_handler(
                None, reply().replace("13760", "13761").encode()
            )

        client.write_gatt_char = AsyncMock(side_effect=respond)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            await device.get_jump_profile_hex(35)
        client.write_gatt_char.assert_awaited_once()
