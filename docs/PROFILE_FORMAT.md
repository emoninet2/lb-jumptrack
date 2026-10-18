# Raw profile and experimental units

There is no confirmed unit-bearing profile decoder in the supplied Java master. It builds `Get Hex Profile in Jump ...`; it does not define a text/altitude variant, the response header, the sample interval, or the sample units. The implementation therefore offers two distinct interpretations without changing the Java port:

- Raw: preserve and plot four-digit hex words as unsigned numbers.
- Experimental units: explicitly assume a pressure scale, then estimate height relative to a chosen reference pressure. This is computed in Python, not returned as altitude by the device.

## Repeat the plot from saved jump 35

From the LB folder:

```bash
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --pressure-scale 0.1 --reference-pressure 1007 --units feet
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --pressure-scale 0.1 --reference-pressure 1007 --units meters
```

The saved profile is sufficient; Bluetooth is not needed. To read a new profile first, replace `--file ...` with `--jump 35` while the device is available. This sends only the master's hex-profile read command. `--address` and `--timeout` override the connection identifier and response timeout.

The pressure assumption is `pressure_hpa = raw_word * 0.1`. The 1007 hPa reference is an explicitly chosen example: the second observed header field is 10070 and the final raw samples are near 10069. This agreement makes the hypothesis plausible, but it does not establish the field meanings, pressure scale, or correct altitude algorithm. No conversion is enabled silently. Both pressure options are required for unit estimates.

For jump 35 these assumptions produce approximately 13,857.5 feet at the first word and 2.7 feet at the last. This is height relative to the model height at the selected reference pressure, **not verified device altitude, measured AGL, or elevation above sea level**. Weather, temperature, the reference choice and the unconfirmed sample encoding affect the result.

## Conversion model

The calculation inverts NASA's [metric troposphere curve fit](https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html). Pressure must be in kPa in this equation:

```text
T = 15.04 - 0.00649*h
p_kPa = 101.29 * ((T + 273.1) / 288.08)^5.256
h_m = (288.14 - 288.08 * (p_kPa / 101.29)^(1/5.256)) / 0.00649
estimated_height_m = h_m(sample_pressure) - h_m(reference_pressure)
feet = meters / 0.3048
```

The code rejects zero or negative pressures, nonfinite parameters, and pressures implying model heights above the troposphere's 11 km boundary. The atmospheric model is a separate extension, not copied from the Java master.

The horizontal axis remains sample index. Supply `--sample-interval SECONDS` only when the real interval is known; it is not inferred from an unidentified header field. No speed is derived.

## Files and API

Outputs default to `jumptrack_data/profile_plots/`:

- `jump_00035.png`: raw-only chart.
- `jump_00035_estimated_feet.png`: raw, assumed pressure and estimated height panels.
- `jump_00035_estimated_feet_samples.csv`: raw values, hex words, assumed hPa, estimated meters and estimated feet.
- `jump_00035_estimated_feet_metadata.json`: untouched numeric header fields, checksum metadata and explicit conversion assumptions.

Unit-specific filenames keep raw and estimated plots separate. Existing matching output filenames are overwritten. Use `--output-dir PATH` to choose another folder and `--show` to display a window if a GUI backend is available. The source input file is not rewritten.

```python
from pathlib import Path
from plot_profile import parse_profile, convert_profile

profile = parse_profile(Path("jumptrack_data/jump_00035_profile.txt").read_text())
raw = profile["raw_words"]
converted = convert_profile(
    profile,
    pressure_scale_hpa=0.1,
    reference_pressure_hpa=1007,
    altitude_unit="feet",
)
print(raw[0], converted["pressure_hpa"][0], converted["estimated_height"][0])
```

The decoder currently assumes the observed 16-decimal-field header and four-digit hex word layout. It preserves every header field without assigning undocumented meanings. The saved response yields 1,216 words; the last header field is 1217, whose meaning is still unknown. Checksums remain unverified. An APK response parser or protocol specification is still needed for confirmed units and sample timing.

## Additional profile-count evidence

Live reads of jumps 33 and 34 confirmed the same relationship as jump 35: jump-list unknown_1 equals the final numeric header field and is one greater than the decoded raw-word count (1274/1273, 1393/1392, 1217/1216). A count/length interpretation is strongly supported; its exact inclusive convention is not confirmed. See PROFILE_COUNT_COMPARISON.md.

## Using the profile count

The API now exposes `profile_count_field` in parsed jump-list rows. `unknown_1` remains an alias for compatibility; `unknown_2` is unchanged. This field matches the final profile header field in all three tested jumps. The exact inclusive counting convention remains unverified.

`parse_profile()` reports `profile_count_field`, `decoded_word_count`, `count_difference`, `count_matches_observed_layout`, and `validation_warnings`. The observed firmware rule is header count = decoded words + 1. A mismatch warns about possible missing/extra data or a different layout; it is not proof of corruption. This is a structural check, not a checksum verification.

```bash
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --strict-count --expected-count 1217
```

`--expected-count` optionally cross-checks the jump-list field against the profile header. `--strict-count` refuses to plot/export when either check fails; otherwise mismatches generate warnings and are stored in metadata JSON. No samples are invented, removed or padded. The field does not establish the sample interval, altitude units, or duration.
