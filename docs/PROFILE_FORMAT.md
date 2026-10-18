# Profile parsing, altitude and vertical speed

`profile_decoder.py` ports the profile conversion found in the recovered
JumpTrack Android 1.1.64 APK. It is independent of Bluetooth and Matplotlib.
`plot_profile.parse_profile` remains a compatible import of the shared parser.
The original downloaded text and header integers are preserved.

## Wire layout and header

A supported response consists of the command echo, 16 decimal header tokens,
four-digit hex words, checksum metadata and EOF. CRC or byte-count mismatches, incomplete responses, malformed
payloads and mismatched echo/header jump numbers are rejected. Physical units
come from the recovered app's `DataProcessor`, `RawBLEJumpData`, `JumpUtils` and
`MeasurementUtils` classes; see [APK audit](APK_AUDIT.md).

| Zero-based field | Meaning | Stored units |
| --- | --- | --- |
| 0 | Jump number | Integer |
| 1 | Ground pressure | Divide by 10 for hPa |
| 2 | Temperature | Divide by 10 for Celsius |
| 3 | Exit altitude | Feet |
| 4 | Recorded deployment altitude | Feet |
| 5 | Freefall duration | Seconds |
| 6–10 | Month, day, year, hour, minute | Device local wall-clock |
| 11 | Average freefall TAS | mph |
| 12 | Average canopy TAS | mph |
| 13 | Maximum freefall TAS | mph |
| 14 | Maximum canopy TAS | mph |
| 15 | Observed profile-count field | Inclusive convention unconfirmed |

Negative temperature values are supported. Decoding rejects invalid dates,
nonpositive ground pressure, zero/invalid pressure samples and unsupported units.
Those checks prevent silently producing a plausible altitude for invalid input.
The stored deployment altitude is exposed directly; no deployment event is
inferred from the altitude/speed curve.

## App-derived conversion

For ground pressure `g` in hPa and raw hex word `w`:

```text
P(p) = (p / 1013.25) ** 0.190263
altitude_ft = (P(g) - P(w / 10)) * 44330.8 * 3.2808
altitude_m = altitude_ft * 0.3048
time_seconds = -2 + sample_index * 0.25
```

The -2-second origin and 0.25-second interval reproduce the app's chart axis;
they do not independently establish the physical exit instant.

Speed is available only when `sample_index > 28`. At or below the recorded
deployment altitude, compare with index minus 12 over 3 seconds. Above it,
compare with index minus 24 over 6 seconds:

```text
speed_mph = ((previous_altitude_ft - current_altitude_ft) / window_seconds) * 0.681818
kmh = mph * 1.609344
fps = mph * 1.46667
mps = mph * 0.44704
```

These constants intentionally match the app. Descending motion is positive;
ascending motion may be negative. Samples 0–28 have null speed/window in JSON
and blank cells in CSV. The app's choice of window creates a possible change in
smoothing at the recorded deployment altitude. No samples are added or padded.

Named header summaries use the app's integer rounding (ties toward positive
infinity). Calculations retain double precision; Android chart points are
converted to floats, so plotted display precision can differ slightly. The
derived speed series is separate from the four stored TAS summary values.
Neither implements a TAS/SAS mode switch or a new SAS conversion.
Human-readable speed labels are neutral ("stored freefall/canopy speed").
JSON retains the APK-derived `tas` names for provenance and compatibility;
those names do not confirm TAS recording. `recording_speed_mode` is null: the app export has no identified mode field,
and the decoder does not infer recording mode from missing or nonzero TAS values.

## CLI and output

```bash
jt logbook profile 33 --format summary
jt logbook profile 33 --format text --units meters --speed-unit kmh
jt --output profile.json logbook profile 33 --format json
jt --output samples.csv logbook profile 33 --format csv
jt logbook profile 33 --file jumptrack_data/jump_00033_profile.txt --format summary
```

The default format remains `hex`. `summary` shows named header values and
warnings; `text` appends the sample CSV; `json` contains headers, summaries,
metadata and all samples. CSV columns include explicit units. `--file` never
connects to Bluetooth, checks the requested jump and refuses to overwrite the
source file via `--output`.

The plotter defaults to three panels (raw, altitude, speed) and marks deployment
altitude. Outputs include `jump_00033_feet_mph.png`, corresponding `_samples.csv`
and `_metadata.json`, plus the raw `_profile.txt`. Use `--units meters` and
`--speed-unit kmh` for another view. Matching output names are overwritten;
source files are preserved, including when they would collide with an export.

## Python API

```python
from pathlib import Path
from profile_decoder import parse_profile, decode_profile

profile = parse_profile(Path("jumptrack_data/jump_00033_profile.txt").read_text())
decoded = decode_profile(profile, altitude_unit="feet", speed_unit="mph")
print(decoded["summary"]["deployment_altitude"])
print(decoded["samples"][29]["vertical_speed"])
# Within an async function, with a connected JumpTrack client:
# decoded = await device.get_jump_profile(33, altitude_unit='meters', speed_unit='kmh')
```

## Count and checksum validation

The observed count rule is header field 15 = decoded words + 1. Jump-list
`profile_count_field` (also retained as `unknown_1`) matches it in three stored
jumps; see [count evidence](PROFILE_COUNT_COMPARISON.md). A mismatch produces
`validation_warnings`; `strict_count=True` or plotter `--strict-count` rejects it.
An optional expected count compares jump list and header. No data is trimmed,
added or padded to force a match.

Structural count validation and wire integrity are separate checks. Profiles
require valid CRC-16/XMODEM and byte-count metadata; damaged or incomplete
responses are rejected before decoding. LF-normalized saved files and leading
empty transport-framing lines are normalized explicitly. Raw captures are not
rewritten. See [integrity details](ACC_AND_INTEGRITY.md). App-derived numerical
parity is tested with an optional Java oracle using the private recovered source.
Independent hardware/physical-altitude verification remains pending.

## Raw and legacy experimental views

`plot_profile.py --raw` plots raw words against sample index. An explicit
`--sample-interval` is allowed only for raw/experimental plots. Supplying both
`--pressure-scale` and `--reference-pressure` selects the older experimental
NASA troposphere model, kept separate from the app port:

```bash
python plot_profile.py --file profile.txt --raw
python plot_profile.py --file profile.txt --pressure-scale 0.1 --reference-pressure 1007 --units meters
```

`convert_profile()` retains that API and its explicit assumptions and 11 km
model limit. Its formula comes from [NASA's troposphere curve](https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html);
it is not the default JumpTrack decoder. No velocity is derived for that legacy
experimental view.
