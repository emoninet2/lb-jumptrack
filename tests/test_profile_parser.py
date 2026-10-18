"""Offline checks for the observed profile decoder; no BLE dependency."""

import unittest

from plot_profile import parse_profile


def reply(payload="173E17402755"):
    return "\r\n".join(
        [
            "Get Hex Profile in Jump 00035",
            *map(
                str,
                [
                    35,
                    10070,
                    205,
                    13760,
                    3390,
                    61,
                    9,
                    27,
                    2026,
                    17,
                    38,
                    123,
                    10,
                    132,
                    16,
                    1217,
                ],
            ),
            payload,
            "CheckSum.Bytes: 00000",
            "CheckSum.Sum: 00000",
            "EOF",
            "",
        ]
    )


class ProfileParserTests(unittest.TestCase):
    def test_words_and_header(self):
        parsed = parse_profile(reply())
        self.assertEqual(parsed["jump_number"], 35)
        self.assertEqual(parsed["raw_words"], [5950, 5952, 10069])
        self.assertEqual(parsed["header_decimal_fields"][-1], 1217)

    def test_split_payload_lines(self):
        self.assertEqual(
            parse_profile(reply("173E\r\n17402755"))["raw_words"], [5950, 5952, 10069]
        )

    def test_observed_count_rule_for_three_profile_sizes(self):
        # Synthetic payloads retain the observed field/count relationships,
        # without publishing personal jump captures.
        for count in [1274, 1393, 1217]:
            with self.subTest(count=count):
                raw = reply("173E" * (count - 1)).replace("1217", str(count))
                parsed = parse_profile(
                    raw, expected_profile_count=count, strict_count=True
                )
                self.assertEqual(parsed["decoded_word_count"], count - 1)
                self.assertTrue(parsed["count_matches_observed_layout"])
                self.assertEqual(parsed["count_difference"], 1)
                self.assertEqual(parsed["validation_warnings"], [])

    def test_missing_and_extra_words_warn_or_fail_in_strict_mode(self):
        valid = reply().replace("1217", "4")
        self.assertTrue(
            parse_profile(valid, strict_count=True)["count_matches_observed_layout"]
        )
        for payload in ["173E1740", "173E174027552755"]:
            raw = reply(payload).replace("1217", "4")
            self.assertTrue(parse_profile(raw)["validation_warnings"])
            with self.assertRaisesRegex(ValueError, "Profile count mismatch"):
                parse_profile(raw, strict_count=True)

    def test_jump_list_header_mismatch(self):
        raw = reply().replace("1217", "4")
        parsed = parse_profile(raw, expected_profile_count=5)
        self.assertTrue(parsed["count_matches_observed_layout"])
        self.assertIn("Jump-list/header", parsed["validation_warnings"][0])
        with self.assertRaisesRegex(ValueError, "Jump-list/header"):
            parse_profile(raw, expected_profile_count=5, strict_count=True)

    def test_jump_list_exposes_count_and_compatibility_alias(self):
        from jumptrack import parse_jump_list

        parsed = parse_jump_list("35,2026,9,27,17,38,1217,15360")[0]
        self.assertEqual(parsed["profile_count_field"], 1217)
        self.assertEqual(parsed["unknown_1"], 1217)
        self.assertEqual(parsed["unknown_2"], 15360)

    def test_invalid_or_incomplete_responses(self):
        for raw in [
            reply().replace("EOF", ""),
            reply("173"),
            reply("ZZZZ"),
            reply("").replace("CheckSum.Bytes: 00000", ""),
            reply().replace("00035", "00034"),
            "EOF",
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_profile(raw)


if __name__ == "__main__":
    unittest.main()
