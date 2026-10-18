"""Decoded header, app-derived samples, exports and an optional source oracle."""

import contextlib
import io
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jumptrack
from profile_decoder import decode_profile, format_profile, parse_profile, profile_csv
from tests.test_java_master_parity import block
from tests.test_profile_parser import reply, seal

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "jumptrack_data/apk_reference/1.1.64/full/sources/com/lb/altimeter/android"
)


def descending_reply():
    words = [6000 + 10 * i for i in range(160)]
    return seal(
        reply("".join(f"{word:04X}" for word in words))
        .replace("3390", "10000")
        .replace("1217", "161")
    )


class DecodedProfileTests(unittest.IsolatedAsyncioTestCase):
    def test_header_and_summary_units(self):
        raw = parse_profile(reply())
        feet = decode_profile(raw)
        meters = decode_profile(raw, altitude_unit="meters", speed_unit="kmh")
        self.assertEqual(feet["summary"]["deployment_altitude"], 3390)
        self.assertEqual(feet["summary"]["exit_altitude"], 13760)
        self.assertEqual(feet["header"]["ground_pressure_hpa"], 1007)
        self.assertEqual(feet["header"]["temperature_c"], 20.5)
        self.assertEqual(feet["summary"]["avg_freefall_tas"], 123)
        self.assertEqual(feet["summary"]["jump_datetime"], "2026-09-27T17:38:00")
        self.assertEqual(
            meters["summary"]["deployment_altitude"], math.floor(3390 * 0.3048 + 0.5)
        )
        self.assertEqual(
            meters["summary"]["avg_freefall_tas"], math.floor(123 * 1.609344 + 0.5)
        )
        self.assertEqual(raw["raw_words"], [5950, 5952, 10069])
        cold = decode_profile(
            parse_profile(seal(reply().replace("\r\n205\r\n", "\r\n-25\r\n")))
        )
        self.assertEqual(cold["header"]["temperature_c"], -2.5)

    def test_timing_missing_speed_and_both_windows(self):
        decoded = decode_profile(parse_profile(descending_reply(), strict_count=True))
        samples = decoded["samples"]
        self.assertEqual([s["time_seconds"] for s in samples[:3]], [-2, -1.75, -1.5])
        self.assertTrue(all(s["vertical_speed"] is None for s in samples[:29]))
        self.assertIsNotNone(samples[29]["vertical_speed"])
        self.assertEqual({s["speed_window_seconds"] for s in samples[29:]}, {3, 6})
        self.assertTrue(all(s["vertical_speed"] > 0 for s in samples[29:]))
        self.assertEqual(decoded["decoded_word_count"], 160)
        self.assertNotIn("None", profile_csv(decoded))
        self.assertIn("vertical_speed_mph", profile_csv(decoded))

    def test_invalid_decode_and_requested_jump(self):
        for raw in [reply("0000"), reply().replace("\r\n10070\r\n", "\r\n0\r\n")]:
            with self.assertRaises(ValueError):
                decode_profile(parse_profile(raw))
        with self.assertRaises(ValueError):
            format_profile(reply(), jump_number=34)
        self.assertIn("Deployment altitude: 3390 feet", format_profile(reply()))

    async def test_offline_cli_formats_preserve_input_and_never_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.txt"
            path.write_bytes(reply().encode())
            before = path.read_bytes()
            with patch.object(jumptrack, "BleakClient") as client:
                for fmt in ("summary", "text", "json", "csv"):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        await jumptrack.main(
                            [
                                "logbook",
                                "profile",
                                "35",
                                "--file",
                                str(path),
                                "--format",
                                fmt,
                            ]
                        )
                    if fmt == "json":
                        self.assertEqual(
                            json.loads(output.getvalue())["summary"][
                                "deployment_altitude"
                            ],
                            3390,
                        )
                    elif fmt == "csv":
                        self.assertTrue(output.getvalue().startswith("sample_index,"))
                    else:
                        self.assertIn(
                            "Deployment altitude: 3390 feet", output.getvalue()
                        )
                client.assert_not_called()
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    await jumptrack.main(
                        [
                            "--output",
                            str(path),
                            "logbook",
                            "profile",
                            "35",
                            "--file",
                            str(path),
                            "--format",
                            "json",
                        ]
                    )
            self.assertEqual(path.read_bytes(), before)

    async def test_client_decoded_profile_reads_once(self):
        with patch.object(jumptrack, "BleakClient"):
            device = jumptrack.JumpTrack(address="test")
        device.get_jump_profile_hex = AsyncMock(return_value=reply())
        decoded = await device.get_jump_profile(
            35, timeout=123, altitude_unit="meters", speed_unit="kmh"
        )
        device.get_jump_profile_hex.assert_awaited_once_with(35, timeout=123)
        self.assertEqual(decoded["summary"]["deployment_altitude"], 1033)

    async def test_live_json_stdout_has_no_transport_logs(self):
        def progress():
            print("Connected")

        with patch.object(jumptrack, "JumpTrack") as cls:
            device = cls.return_value
            device.connect = AsyncMock(side_effect=progress)
            device.disconnect = AsyncMock(side_effect=progress)
            device.get_jump_profile_hex = AsyncMock(return_value=reply())
            output = io.StringIO()
            errors = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                await jumptrack.main(
                    [
                        "--address",
                        "test",
                        "logbook",
                        "profile",
                        "35",
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(
                json.loads(output.getvalue())["summary"]["deployment_altitude"], 3390
            )
            self.assertIn("Connected", errors.getvalue())
            self.assertFalse(cls.call_args.kwargs["allow_writes"])
            device.disconnect.assert_awaited_once()

    @unittest.skipUnless(
        (SOURCE / "presentation/utils/JumpUtils.java").exists()
        and shutil.which("java")
        and shutil.which("javac"),
        "Private app source and JDK required",
    )
    def test_conversion_against_recovered_java_method_bodies(self):
        source = (SOURCE / "presentation/utils/JumpUtils.java").read_text()
        measurement = (SOURCE / "utils/MeasurementUtils.java").read_text()
        mapping = block(
            source,
            source.index("public static final /* synthetic */ class WhenMappings"),
        )
        names = [
            "private final double prepareAltitudeValue(",
            "private final double calculateP(",
            "private final double prepareSpeedBy6Seconds(",
            "private final double prepareSpeedBy3Seconds(",
            "public final double translateSpeed(",
        ]
        methods = "\n".join(block(source, source.index(name)) for name in names)
        conversions = "\n".join(
            block(measurement, measurement.index("public final double " + name + "("))
            for name in [
                "mileHourToKilometerHour",
                "mileHourToFeetSecond",
                "mileHourToMeterSecond",
            ]
        )
        java = (
            """enum SpeedUOM {MILE_HOUR,KILOMETER_HOUR,FEET_SECONDS,METER_SECOND}
        enum DistanceUOM {FEET,METERS}
        class NoWhenBranchMatchedException extends RuntimeException {}
        class Intrinsics { static void checkNotNullParameter(Object o,String n) {} }
        class MeasurementUtils {static final MeasurementUtils INSTANCE = new MeasurementUtils();
        """
            + conversions
            + "}\npublic class ProfileOracle {\n"
            + mapping
            + methods
        )
        java += """public static void main(String[] args) {
          ProfileOracle p = new ProfileOracle();
          double[] a = new double[160];
          for(int i=0;i<160;i++) a[i]=p.prepareAltitudeValue(p.calculateP(1007),6000+10*i);
          for(SpeedUOM u:SpeedUOM.values()) for(int i=0;i<160;i++) {
            double v=i<=28 ? Double.NaN : a[i]<=10000 ? p.prepareSpeedBy3Seconds(a[i],a[i-12],u) : p.prepareSpeedBy6Seconds(a[i],a[i-24],u);
            System.out.println(u+","+i+","+a[i]+","+v);
          }
        }}"""
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "ProfileOracle.java").write_text(java)
            subprocess.run(
                ["javac", "ProfileOracle.java"],
                cwd=folder,
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                ["java", "-cp", folder, "ProfileOracle"],
                check=True,
                capture_output=True,
                text=True,
            )
        units = {
            "MILE_HOUR": "mph",
            "KILOMETER_HOUR": "kmh",
            "FEET_SECONDS": "fps",
            "METER_SECOND": "mps",
        }
        decoded = {
            u: decode_profile(parse_profile(descending_reply()), speed_unit=u)[
                "samples"
            ]
            for u in units.values()
        }
        for line in result.stdout.splitlines():
            unit, index, altitude, speed = line.split(",")
            sample = decoded[units[unit]][int(index)]
            self.assertAlmostEqual(sample["altitude"], float(altitude), places=7)
            if int(index) <= 28:
                self.assertIsNone(sample["vertical_speed"])
            else:
                self.assertAlmostEqual(sample["vertical_speed"], float(speed), places=7)
