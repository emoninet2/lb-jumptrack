"""JumpTrack 1.1.64 profile parsing and app-derived altitude/speed decoding.

Independent of Bluetooth and plotting. Wire checksums and byte counts are verified when parsing profiles.
App formulas are traced in docs/APK_AUDIT.md; no samples are invented or padded.
"""

import csv
import io
import json
import math
import re
from datetime import datetime

from wire_protocol import verify_response

SAMPLE_INTERVAL_SECONDS = 0.25
START_TIME_SECONDS = -2.0
SPEED_FACTORS = {"mph": 1.0, "kmh": 1.609344, "fps": 1.46667, "mps": 0.44704}


def parse_profile(raw, *, expected_profile_count=None, strict_count=False):
    """Parse the layout observed in the saved PROTRACK 3 firmware 01.04 reply.

    Observed layout: command echo, 16 decimal header lines, then hex words,
    checksum metadata, EOF. Preserve raw header fields; named decoding is provided by decode_profile().
    CRC and byte-count metadata are required and verified.
    """
    checksum = verify_response(raw, required=True)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines or not re.fullmatch(r"Get Hex Profile in Jump -?[0-9]+", lines[0]):
        raise ValueError("Expected a Get Hex Profile in Jump response")
    if lines[-1] != "EOF":
        raise ValueError("Incomplete profile response: missing final EOF")
    checksum_start = next(
        (i for i, line in enumerate(lines) if line.startswith("CheckSum.")), None
    )
    if checksum_start is None:
        raise ValueError("Missing checksum metadata boundary")
    header = lines[1:17]
    if len(header) != 16 or any(
        not re.fullmatch(r"-?[0-9]+", field) for field in header
    ):
        raise ValueError("Unrecognized profile header: expected 16 decimal fields")
    requested_jump = int(lines[0].split()[-1])
    if int(header[0]) != requested_jump:
        raise ValueError("Echoed jump number does not match the profile header")
    payload_lines = lines[17:checksum_start]
    if not payload_lines:
        raise ValueError("Profile contains no hex data")
    if any(not re.fullmatch(r"(?:[0-9A-Fa-f]{4})+", line) for line in payload_lines):
        raise ValueError("Malformed hex payload: expected groups of four hex digits")
    encoded = "".join(payload_lines)
    words = [int(encoded[i : i + 4], 16) for i in range(0, len(encoded), 4)]
    declared_count = int(header[-1])
    decoded_count = len(words)
    warnings = []
    matches_observed = declared_count == decoded_count + 1
    if not matches_observed:
        warnings.append(
            f"Profile count mismatch: header={declared_count}, decoded={decoded_count}; "
            "observed firmware layout expects header = decoded + 1. "
            "Possible missing/extra data or a different profile layout."
        )
    if expected_profile_count is not None:
        if (
            isinstance(expected_profile_count, bool)
            or not isinstance(expected_profile_count, int)
            or expected_profile_count < 0
        ):
            raise ValueError("expected_profile_count must be a nonnegative integer")
        if expected_profile_count != declared_count:
            warnings.append(
                f"Jump-list/header count mismatch: list={expected_profile_count}, header={declared_count}"
            )
    if strict_count and warnings:
        raise ValueError("; ".join(warnings))
    return {
        "profile_count_field": declared_count,
        "decoded_word_count": decoded_count,
        "count_difference": declared_count - decoded_count,
        "count_matches_observed_layout": matches_observed,
        "expected_profile_count": expected_profile_count,
        "validation_warnings": warnings,
        "jump_number": requested_jump,
        "header_decimal_fields": [int(field) for field in header],
        "raw_words": words,
        "checksum_metadata": lines[checksum_start:-1],
        "checksum": checksum,
        "interpretation": "Raw 16-bit pressure words; see decode_profile for JumpTrack 1.1.64 interpretation",
    }


def decode_profile(profile, *, altitude_unit="feet", speed_unit="mph"):
    """Reproduce the recovered app's conversion and speed-window selection.

    Values retain double precision; Android chart points use float precision.
    Header summary distances and TAS values use the app's integer rounding.
    Derived speed is positive for descent; this does not select TAS/SAS mode.
    """
    if altitude_unit not in ("feet", "meters") or speed_unit not in SPEED_FACTORS:
        raise ValueError("Unsupported altitude or speed unit")
    h = profile["header_decimal_fields"]
    if len(h) != 16 or any(type(v) is not int for v in h):
        raise ValueError("Expected 16 integer profile header fields")
    if h[1] <= 0:
        raise ValueError("Ground pressure must be positive")
    timestamp = datetime(h[8], h[6], h[7], h[9], h[10]).isoformat()
    header = {
        "jump_number": h[0],
        "ground_pressure_hpa": h[1] / 10,
        "temperature_c": h[2] / 10,
        "exit_altitude_ft": h[3],
        "deployment_altitude_ft": h[4],
        "freefall_time_seconds": h[5],
        "jump_datetime": timestamp,
        "avg_freefall_tas_mph": h[11],
        "avg_canopy_tas_mph": h[12],
        "max_freefall_tas_mph": h[13],
        "max_canopy_tas_mph": h[14],
    }
    words = profile["raw_words"]
    if any(type(word) is not int or not 0 < word <= 65535 for word in words):
        raise ValueError("Pressure samples must be nonzero unsigned 16-bit integers")
    ground = (header["ground_pressure_hpa"] / 1013.25) ** 0.190263
    altitudes_ft = [
        (ground - ((word / 10) / 1013.25) ** 0.190263) * 44330.8 * 3.2808
        for word in words
    ]
    distance_factor = 1.0 if altitude_unit == "feet" else 0.3048
    factor = SPEED_FACTORS[speed_unit]
    samples = []
    for index, (word, altitude_ft) in enumerate(zip(words, altitudes_ft)):
        speed = None
        window = None
        if index > 28:
            window = 3 if altitude_ft <= header["deployment_altitude_ft"] else 6
            previous = altitudes_ft[index - int(window / SAMPLE_INTERVAL_SECONDS)]
            speed = ((previous - altitude_ft) / window) * 0.681818 * factor
        samples.append(
            {
                "sample_index": index,
                "time_seconds": START_TIME_SECONDS + index * SAMPLE_INTERVAL_SECONDS,
                "raw_value": word,
                "hex_word": f"{word:04X}",
                "pressure_hpa": word / 10,
                "altitude": altitude_ft * distance_factor,
                "vertical_speed": speed,
                "speed_window_seconds": window,
            }
        )

    # Kotlin roundToLong/roundToInt rounds ties toward positive infinity.
    def rounded(value):
        return math.floor(value + 0.5)

    summary = {
        "exit_altitude": rounded(h[3] * distance_factor),
        "deployment_altitude": rounded(h[4] * distance_factor),
        "freefall_time_seconds": h[5],
        "jump_datetime": timestamp,
    }
    for name, index in (
        ("avg_freefall_tas", 11),
        ("avg_canopy_tas", 12),
        ("max_freefall_tas", 13),
        ("max_canopy_tas", 14),
    ):
        summary[name] = rounded(h[index] * factor)
    return {
        "jump_number": h[0],
        "decoder": "JumpTrack Android 1.1.64 (app-derived)",
        "altitude_unit": altitude_unit,
        "speed_unit": speed_unit,
        "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "start_time_seconds": START_TIME_SECONDS,
        "speed_convention": "positive descent; app-derived 3/6-second altitude differences",
        "checksum_verified": profile.get("checksum", {}).get("verified", False),
        "checksum": profile.get("checksum"),
        "recording_speed_mode": None,
        "recording_speed_mode_status": "No TAS/SAS recording-mode field identified in the exported header",
        "header": header,
        "summary": summary,
        "samples": samples,
        "profile_count_field": profile["profile_count_field"],
        "decoded_word_count": profile["decoded_word_count"],
        "validation_warnings": profile["validation_warnings"],
    }


def format_profile(
    raw,
    *,
    output_format="summary",
    altitude_unit="feet",
    speed_unit="mph",
    jump_number=None,
):
    """Format a downloaded or saved response without changing the source data."""
    if output_format == "hex":
        return raw
    profile = parse_profile(raw)
    if jump_number is not None and profile["jump_number"] != jump_number:
        raise ValueError("Requested jump does not match the saved profile")
    decoded = decode_profile(
        profile, altitude_unit=altitude_unit, speed_unit=speed_unit
    )
    if output_format == "json":
        return json.dumps(decoded, indent=2, allow_nan=False)
    if output_format == "csv":
        return profile_csv(decoded)
    if output_format not in ("summary", "text"):
        raise ValueError("Unsupported profile output format")
    result = format_profile_summary(decoded)
    if output_format == "text":
        result += "\n\n" + profile_csv(decoded)
    return result


def format_profile_summary(decoded):
    summary = decoded["summary"]
    distance = decoded["altitude_unit"]
    speed = decoded["speed_unit"]
    lines = [
        f"Jump {decoded['jump_number']} — {summary['jump_datetime']}",
        f"Exit altitude: {summary['exit_altitude']} {distance}",
        f"Deployment altitude: {summary['deployment_altitude']} {distance}",
        f"Freefall time: {summary['freefall_time_seconds']} seconds",
        f"Stored freefall speed: average {summary['avg_freefall_tas']}, maximum {summary['max_freefall_tas']} {speed}",
        f"Stored canopy speed: average {summary['avg_canopy_tas']}, maximum {summary['max_canopy_tas']} {speed}",
        f"Samples: {decoded['decoded_word_count']}; interval 0.25 seconds; chart starts at -2 seconds",
        f"Decoder: JumpTrack 1.1.64 formulas; checksum {'verified' if decoded['checksum_verified'] else 'unverified'}",
        "Recorded TAS/SAS mode: unknown (no exported mode field identified)",
    ]
    lines.extend("WARNING: " + warning for warning in decoded["validation_warnings"])
    return "\n".join(lines)


def profile_csv(decoded):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "sample_index",
            "time_seconds",
            "raw_value",
            "hex_word",
            "pressure_hpa",
            "altitude_" + decoded["altitude_unit"],
            "vertical_speed_" + decoded["speed_unit"],
            "speed_window_seconds",
        ]
    )
    for sample in decoded["samples"]:
        writer.writerow(
            [
                sample[key]
                for key in (
                    "sample_index",
                    "time_seconds",
                    "raw_value",
                    "hex_word",
                    "pressure_hpa",
                    "altitude",
                    "vertical_speed",
                    "speed_window_seconds",
                )
            ]
        )
    return stream.getvalue().rstrip("\r\n")
