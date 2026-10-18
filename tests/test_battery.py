"""Device-exported voltage and battery status, without percentage estimates."""

import unittest

from jumptrack import parse_battery_information, parse_warning_configuration


class BatteryTests(unittest.TestCase):
    def test_status_codes_match_apk_icons(self):
        for code, status in [
            (1, "Full"),
            (2, "Half"),
            (3, "Almost empty"),
            (4, "Critical"),
        ]:
            with self.subTest(code=code):
                result = parse_battery_information(
                    f"Battery: 5.4 Volt, {code}\r\nEOF\r\n"
                )
                self.assertEqual(result["voltage"], 5.4)
                self.assertEqual(result["status_code"], code)
                self.assertEqual(result["status"], status)

    def test_unknown_missing_and_malformed_do_not_invent_status(self):
        for raw in [
            "",
            "Battery:\nEOF\n",
            "Battery: garbage",
            "Battery: 5.4 Volt",
            "Battery: 5.4 Volt, 9",
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_battery_information(raw)["status"], "Unknown")
        self.assertEqual(
            parse_battery_information("Battery: 5.4 Volt, 9")["status_code"], 9
        )

    def test_warning_configuration_preserves_raw_battery(self):
        config = parse_warning_configuration("R-00\r\nBattery: 5.4 Volt, 2\r\nEOF\r\n")
        self.assertEqual(config["battery"], "5.4 Volt, 2")
        self.assertEqual(config["battery_info"]["status"], "Half")
