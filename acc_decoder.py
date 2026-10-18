"""ACC decoding from JumpTrack 1.1.64; scalar g samples, not XYZ vectors."""

import csv
import io
import json
import re

from wire_protocol import verify_response


def decode_acc(raw, *, expected=None):
    checksum = verify_response(raw, required=True)
    lines = [s.strip() for s in raw.splitlines() if s.strip()]
    match = (
        re.fullmatch(r"Get Hex xACC (-?[0-9]+) (-?[0-9]+) (-?[0-9]+)", lines[0])
        if lines
        else None
    )
    if match is None:
        raise ValueError(
            "ACC decoding requires a Get Hex xACC response; text ACC layout is unverified"
        )
    jump, start, duration = map(int, match.groups())
    if expected is not None and (jump, start, duration) != tuple(expected):
        raise ValueError("ACC response parameters do not match the request")
    boundary = next(
        (i for i, line in enumerate(lines) if line.startswith("CheckSum.")), None
    )
    payload = lines[1:boundary]
    if any(re.fullmatch(r"(?:[0-9a-fA-F]{4})+", line) is None for line in payload):
        raise ValueError("Malformed ACC payload: expected four-digit hex words")
    encoded = "".join(payload)
    words = [int(encoded[i : i + 4], 16) for i in range(0, len(encoded), 4)]
    samples = [
        {
            "sample_index": i,
            "time_seconds": start + i * 0.02,
            "raw_value": word,
            "hex_word": f"{word:04X}",
            "sentinel": word == 65535,
            "acceleration_g": (0 if word == 65535 else word) / 256.0,
        }
        for i, word in enumerate(words)
    ]
    return {
        "jump_number": jump,
        "start_time_seconds": start,
        "requested_duration_seconds": duration,
        "sample_interval_seconds": 0.02,
        "sample_count": len(words),
        "status": "data" if words else "empty response",
        "checksum_verified": checksum["verified"],
        "checksum": checksum,
        "decoder": "JumpTrack Android 1.1.64 (app-derived)",
        "samples": samples,
    }


def acc_csv(decoded):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    columns = [
        "sample_index",
        "time_seconds",
        "raw_value",
        "hex_word",
        "acceleration_g",
        "sentinel",
    ]
    writer.writerow(columns)
    writer.writerows([[s[key] for key in columns] for s in decoded["samples"]])
    return stream.getvalue().rstrip("\r\n")


def format_acc(raw, *, output_format="summary", expected=None):
    decoded = decode_acc(raw, expected=expected)
    if output_format == "json":
        return json.dumps(decoded, indent=2, allow_nan=False)
    if output_format == "csv":
        return acc_csv(decoded)
    if output_format not in ("summary", "text"):
        raise ValueError("Unsupported ACC output format")
    result = (
        f"Jump {decoded['jump_number']} ACC: {decoded['sample_count']} samples; "
        f"start {decoded['start_time_seconds']}s; interval 0.02s; checksum verified"
    )
    if not decoded["samples"]:
        result += "\nDevice returned no ACC samples; none were fabricated."
    if output_format == "text":
        result += "\n\n" + acc_csv(decoded)
    return result
