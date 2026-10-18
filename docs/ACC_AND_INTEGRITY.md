# ACC decoding and UART integrity

## Integrity

`wire_protocol.verify_response()` reproduces the CRC calculation from the
recovered `CheckSumUtils`. CRC-16/XMODEM (polynomial 0x1021, initial value zero)
is calculated over UTF-8 bytes preceding `CheckSum`. The received `CheckSum.Sum`
is compared against it, and `CheckSum.Bytes` must equal that payload's byte count.
The app checks CRC; Python additionally checks the advertised byte count.

When metadata is present, live transport rejects mismatches before returning
results. It never retries automatically, including after writes. Non-checksummed
ACK responses remain usable for existing commands and are not called verified.
Decoded profile/ACC file inputs require complete checksum metadata and final EOF.

Text-mode reads can turn CRLF into LF. Checks reconstruct CRLF and remove only
leading blank framing lines, preserving content spaces and interior blank lines.
The returned metadata records `framing_normalized`. This handling validated all
200 original TAS/SAS register-scan captures without rewriting them. A valid CRC
is transfer-integrity evidence, not proof of physical measurement accuracy.

## ACC source mapping

`JumpUtils.decodeHexAcc()` and `prepareAccEntries()` define:

- Four hex characters per unsigned word.
- `FFFF` becomes zero; Python also retains the original word and a sentinel flag.
- Acceleration = decoded word / 256, in the app's scalar g scale.
- Time = requested start + sample index × 0.02 seconds.

`AccelerationActivity` uses a g-value formatter for this series. This is a
scalar acceleration trace, not a decoded three-axis vector. It is not integrated
to replace the barometric speed or altitude trace. Android plots float values;
Python retains higher precision for timestamps. `AccUtils` aligns existing
altitude/speed entries with ACC for an optional overlay; the Python ACC tool
provides a standalone g chart rather than that presentation-specific axis scaling.

```bash
python jumptrack.py logbook acc 33 0 60 --decode summary
python jumptrack.py logbook acc 33 0 60 --decode json
python jumptrack.py --output acc.csv logbook acc 33 0 60 --decode csv
python jumptrack.py logbook acc 33 0 60 --file acc.txt --decode text
python plot_acc.py --file acc.txt
python plot_acc.py --jump 33 --start 0 --duration 60
```

Global address configuration applies to live reads. The raw `--format hex`
default remains unchanged; `--format text` retrieves the other wire representation
but its payload decoder is not established. Combining it with `--decode` is rejected.
`--file` uses the supplied jump/start/duration to check that the saved response
matches. The input cannot be overwritten by `--output`.

The plotter exports raw response, JSON, CSV and PNG under `jumptrack_data/acc_plots/`.
It refuses source/output collisions. Matching generated outputs may be overwritten.
An empty device response produces zero samples and no fabricated chart. No
nonempty hardware ACC capture has yet been independently validated; synthetic
cases and recovered Java method execution establish algorithmic parity only.

## Python API

```python
from acc_decoder import decode_acc

data = decode_acc(saved_response, expected=(33, 0, 60))
# With a connected client:
# data = await device.get_acc_decoded(33, 0, 60)
```
