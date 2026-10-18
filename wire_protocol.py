"""UART response integrity checks derived from JumpTrack's CheckSumUtils.

CRC-16/XMODEM, initial value zero, over UTF-8 bytes preceding CheckSum metadata.
"""

import binascii
import re


def verify_response(raw, *, required=False):
    """Validate available CRC/byte-count metadata; never alter the caller's text.

    Text-mode file reads may normalize CRLF, and an earlier EOF can leave blank
    framing lines. Reconstruct CRLF and remove leading empty lines only; content
    spaces and all interior blank lines remain part of the checksum.
    """
    if not isinstance(raw, str):
        raise TypeError("UART response must be text")
    canonical = (
        raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n").replace("\n", "\r\n")
    )
    if "CheckSum" not in canonical:
        if required:
            raise ValueError("Missing UART checksum metadata")
        return {"verified": False, "status": "not supplied"}
    sums = re.findall(r"(?m)^CheckSum\.Sum: ([0-9]{5})\r?$", canonical)
    counts = re.findall(r"(?m)^CheckSum\.Bytes: ([0-9]{5,})\r?$", canonical)
    if len(sums) != 1 or len(counts) != 1:
        raise ValueError("Missing, ambiguous or malformed UART checksum metadata")
    if not canonical.rstrip().endswith("\r\nEOF"):
        raise ValueError("Incomplete UART response: missing final EOF")
    boundary = canonical.index("CheckSum")
    prefix = canonical[:boundary].encode("utf-8")
    expected, expected_bytes = int(sums[0]), int(counts[0])
    actual = binascii.crc_hqx(prefix, 0)
    if expected != actual or expected_bytes != len(prefix):
        raise ValueError(
            f"UART checksum mismatch: CRC {actual:05d}/{expected:05d}, bytes {len(prefix)}/{expected_bytes}; no retry sent"
        )
    return {
        "verified": True,
        "status": "valid",
        "algorithm": "CRC-16/XMODEM",
        "crc16": actual,
        "payload_bytes": len(prefix),
        "framing_normalized": canonical != raw,
    }
