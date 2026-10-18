# JumpTrack 1.1.64 APK audit

Recovered on 2026-10-18 from the user-supplied XAPK for
`com.lb.altimeter.android`, version 1.1.64. No app was installed or executed and
no Bluetooth operations were performed. JADX 1.5.6 reconstructed Java from the
Kotlin/Dalvik bytecode in `classes9.dex`.

The private source is `UARTCommandBuilder.java` at the repository root, ignored
by Git. Related reconstructed files, the original APK, hashes, and provenance
are under the ignored `jumptrack_data/apk_reference/1.1.64/` directory. They are
not included in the public repository.

## Builder coverage

All 40 public command signatures (38 unique method names), both overload pairs,
and all scalar constants match the saved manifest. The independent Java harness
executed the recovered builder method bodies against 663 inputs; every result
matched the Python implementation. Original-name asynchronous methods and CLI
JSON dispatch are covered by the existing tests.

The builder has these retrieval paths:

| Data | Wire command |
| --- | --- |
| Device information | `Who?` |
| Jump count | `Get Jump Counter` |
| Speed units | `R-38` |
| Settings groups | `R-40`, `R-41`, `R-42` |
| Profile | `Get Hex Profile in Jump NUMBER` |
| ACC, text | `Get xACC NUMBER START DURATION` |
| ACC, hex | `Get Hex xACC NUMBER START DURATION` |
| Warning configuration (constant) | `R-00` |
| Jump list (constant) | `Get New Jump List` |

There are no separate altitude-sample or speed-sample methods in this builder.
This coverage statement applies to that class, not every feature in the APK.
For example, other app classes recognize R-37 total-freefall-time responses.

## Newly identified profile processing

`presentation/utils/JumpUtils.java` contains the app's local altitude and speed
conversion. Relevant reconstructed methods are complete and contain these rules:

- Split the hex profile into groups of four digits.
- Interpret each value divided by 10 as the pressure input.
- Compute `P(p) = (p / 1013.25) ** 0.190263`.
- Compute altitude in feet as
  `(P(ground_pressure) - P(raw_value / 10)) * 44330.8 * 3.2808`.
- Altitude chart sample times start at -2 seconds and advance by 0.25 seconds.
- Speed samples begin at index 29 (`index > 28`).
- At or below deployment altitude, use the altitude difference over 12 samples
  (3 seconds); above deployment altitude, use 24 samples (6 seconds).
- Convert descending feet/second to mph with the app's factor 0.681818, then
  apply the requested speed units. Altitude likewise converts to requested units.

`data/DataProcessor.java` parses the profile header, divides the ground-level
pressure field by 10, and extracts hex payload after the first 16 header tokens.
`JumpUtils.mapData()` uses stored ground pressure and deployment altitude when
preparing the charts.

These formulas and timing are source evidence, not a hardware validation of the
Python decoder. The Python decoder and default plotter now port these formulas and timing.
An optional Java oracle compares the extracted conversion method bodies with
Python across 160 samples and four speed units (640 combinations). There is no need for a separate
velocity-download command to reproduce the app's locally derived speed chart.

## Profile header fields

`DataProcessor.parseRawData()` and `data/RawBLEJumpData.java` identify the first
15 header tokens as: jump number; ground pressure (divided by 10); temperature
(divided by 10); exit altitude; deployment altitude; freefall time; month; day;
year; hour; minute; average freefall TAS; average canopy TAS; maximum freefall
TAS; maximum canopy TAS. Token 15 is skipped when extracting the hex payload.

Thus altitude and TAS summary values are already present in the profile response;
they do not require separate retrieval commands. The Python decoder now exposes these named fields, including recorded
deployment altitude and the four TAS summaries, while retaining raw headers.
Do not confuse TAS summary fields with the separate device TAS/SAS display-mode
setting, which remains unidentified.

## Text profile evidence

`bleuart/UARTOutputType.java` recognizes both `Get Profile in Jump` and
`Get Hex Profile in Jump`. `UARTResponseHandler` routes responses by these
prefixes, and `BLEManager` recognizes both for profile-transfer errors.

The command builder contains only the hex request method. The examined code
does not establish a text request's exact construction, units, active call path,
or acceptance on the tested hardware. A response prefix alone is insufficient
to claim that a usable text-altitude command is implemented or verified.

## Decompilation limits

The builder extracted successfully, and its method bodies compiled in the
independent oracle harness with the existing dependency stubs. Broad extraction
of classes9 alone reported 1,097 errors elsewhere, including unresolved classes
from other DEX files and difficult decompilation. The entire APK has not been
proven to decompile cleanly. Further feature work must inspect the relevant
methods and dependencies rather than treat the whole reconstructed tree as
verified source.

## Follow-up audit and implementation

All ten DEX files and APK resources were loaded for a second, dependency-complete
extraction. Output is under `jumptrack_data/apk_reference/1.1.64/full/` (ignored).
The broad extraction reported seven errors, down from 1,097 with classes9 alone.
The remaining errors are in Compose/Exif/Amplify code and logbook-sharing,
user-defaults networking, and a logbook-activity method. None is in the audited
builder, checksum, UART profile parser, ACC decoder, JumpUtils conversion or
settings methods. This is a targeted protocol audit, not a full app reimplementation.

CRC-16/XMODEM, byte-count verification, ACC scalar decoding and standalone ACC
charts are now implemented. Optional source-oracle tests compare 256 byte-array
CRC cases and 256 ACC words (including FFFF) against recovered Java method bodies.
The profile oracle compares 640 sample/unit cases; the command oracle covers 663
builder cases. All 200 saved register-scan replies verify after explicit framing
normalization; two TAS replies had leading blank framing from the prior response.

### TAS/SAS recording evidence

The user reports that the physical logbook displays speed for a TAS-recorded
jump when the device is in TAS mode, but not when it is switched to SAS. That
supports investigating a per-jump distinction; it has not been independently
reproduced or identified in the Bluetooth export.

No SAS setting, SAS conversion, or per-jump TAS/SAS flag was identified in the
examined app protocol classes or app strings/resources. The exported header
fields named avg/max TAS are preserved as such; their names do not establish
the device's recording mode. The decoder reports `recording_speed_mode: null`
and does not classify a jump using zero/nonzero speed values. A firmware-held
flag not exported by this app remains possible.

Remaining hardware tasks are to compare complete downloads of the same jump
with each mode selected, compare decoded values with the official app/device,
and obtain a known SAS-recorded jump for contrast. These require user-controlled
Bluetooth activation and device settings. Text-profile request acceptance and
actual nonempty ACC retrieval also remain unverified on hardware.
