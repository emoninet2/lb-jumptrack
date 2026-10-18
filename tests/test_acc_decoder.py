"""ACC scalar decoding, empty responses and offline CLI behavior."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jumptrack
from acc_decoder import decode_acc, format_acc
from tests.test_profile_parser import seal


def acc_reply(payload="000001000200FFFF"):
    return seal(
        "Get Hex xACC 00033 005 060\r\n" + (payload + "\r\n" if payload else "")
    )


class AccDecoderTests(unittest.IsolatedAsyncioTestCase):
    def test_scale_timing_sentinel_and_integrity(self):
        decoded = decode_acc(acc_reply(), expected=(33, 5, 60))
        self.assertEqual(
            [s["acceleration_g"] for s in decoded["samples"]], [0, 1, 2, 0]
        )
        self.assertEqual(
            [s["time_seconds"] for s in decoded["samples"]], [5, 5.02, 5.04, 5.06]
        )
        self.assertEqual(decoded["samples"][-1]["raw_value"], 65535)
        self.assertTrue(decoded["samples"][-1]["sentinel"])
        self.assertTrue(decoded["checksum_verified"])

    def test_empty_malformed_and_parameter_mismatch(self):
        self.assertEqual(decode_acc(acc_reply(""))["samples"], [])
        self.assertIn("no ACC samples", format_acc(acc_reply("")))
        for raw in [
            acc_reply("123"),
            acc_reply("XYZX"),
            acc_reply().replace("Hex xACC", "xACC"),
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_acc(raw)
        with self.assertRaises(ValueError):
            decode_acc(acc_reply(), expected=(34, 5, 60))

    async def test_offline_cli_no_client_and_input_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "acc.txt"
            path.write_bytes(acc_reply().encode())
            original = path.read_bytes()
            with patch.object(jumptrack, "BleakClient") as client:
                for fmt in ("summary", "text", "json", "csv"):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        await jumptrack.main(
                            [
                                "logbook",
                                "acc",
                                "33",
                                "5",
                                "60",
                                "--file",
                                str(path),
                                "--decode",
                                fmt,
                            ]
                        )
                    if fmt == "json":
                        self.assertEqual(json.loads(out.getvalue())["sample_count"], 4)
                    else:
                        self.assertTrue(out.getvalue())
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    await jumptrack.main(
                        [
                            "logbook",
                            "acc",
                            "33",
                            "5",
                            "60",
                            "--format",
                            "text",
                            "--decode",
                            "json",
                        ]
                    )
                client.assert_not_called()
            self.assertEqual(path.read_bytes(), original)

    def test_recording_mode_is_not_guessed_from_speed_values(self):
        from profile_decoder import decode_profile, parse_profile
        from tests.test_profile_parser import reply

        for raw in [reply(), seal(reply().replace("\r\n123\r\n", "\r\n0\r\n"))]:
            self.assertIsNone(
                decode_profile(parse_profile(raw))["recording_speed_mode"]
            )
