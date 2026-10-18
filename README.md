# lb-jumptrack-python

Unofficial BLE UART client based on the supplied Android `UARTCommandBuilder.java`. Every command family in that file is exposed through the CLI. This covers command construction, not every feature or response decoder in the Android app.


## Java master parity

`UARTCommandBuilder.java` is the authority and has not been modified. The Python API now exposes **all 40 public Java method signatures (38 unique method names)**, all eight scalar constants (including generated `$stable`), both overload pairs, enum mappings, and original validation/null behavior. `docs/JAVA_MASTER_PARITY.md` contains a complete method-by-method map and verification details.

`java_uart_command_builder.py` contains the source-faithful implementation. `uart_command_builder.py` retains the existing Python-friendly names as adapters to it. No alternate command rules are maintained in those adapters.

The CLI can call original Java method names directly, using a JSON array of arguments:

```bash
.venv/bin/python jumptrack.py constants
.venv/bin/python jumptrack.py --dry-run java prepareSetDistanceUOM '["METERS"]'
.venv/bin/python jumptrack.py --dry-run java prepareSendFlightWarningsCommand '[["1000","2000","3000"]]'
.venv/bin/python jumptrack.py --dry-run java prepareSendFlightWarningsCommand '[2,["1000","2000","3000","4000"]]'
.venv/bin/python jumptrack.py --dry-run java prepareSetTotalFreeFallTimeCommand '["+100000","-2","03"]'
.venv/bin/python jumptrack.py java prepareLoadLumpProfileCommandHex '[35]'
```

Enum arguments use the exact member names listed below; booleans are JSON `true`/`false`; warning lists contain strings. A Calendar argument is represented by an ISO datetime string. Omit the JSON array for no-argument methods, or supply `[]`. Both Java freefall-time overloads are available: three JSON numbers or three strings. Do not mix the two types.

| Java enum | Names implemented from references in the master |
| --- | --- |
| `DistanceUOM` | `FEET`, `METERS` |
| `SpeedUOM` | `MILE_HOUR`, `KILOMETER_HOUR`; `FEET_SECONDS` and `METER_SECOND` raise `Wrong UOM`, exactly as Java does. |
| `DeviceBLEMode` | `AUTOMATIC`, `ECONOMY` |
| `DeviceDiveType` | `DEFAULT`, `_3_SECONDS`, `SLOW`, `SUPER_SLOW` |
| `DeviceTemperatureUnits` | `CELSIUS`, `FAHRENHEIT` |
| `DateFormat` | `EU` -> zero; `US` is the adapter for the non-EU branch -> one. The external enum declaration was not supplied. |

The original Java builder returns `null` for certain invalid warning lists, banks, sound parameters and altitudes. The Python builder returns `None`. A CLI dry-run prints `null`; a live CLI invocation rejects that result **before constructing a BLE client**. The original-named asynchronous API returns `None` without sending. Existing Python-friendly transport methods reject a null command with `ValueError`.

Java formatting widths are **minimums**, not limits: `%05d` can produce six or more digits and includes the sign in its minimum width. The previous Python-only limits have been removed. Unrestricted Java `int` inputs accept -2147483648 through 2147483647, and the altitude argument is a signed 64-bit `long` before its explicit 0–65000 validation. Firmware acceptance of every command the master can construct is not established.

Warning lists shorter than three or containing a nonnumeric item produce null. Exactly four values produce four altitude fields. Any other valid list length of at least three, including more than four, produces a leading zero plus the first three values. Java validates all items as numeric but only parses values it uses; numeric overflow in an unused extra item is therefore ignored, matching the master.

The CLI retains its original read/write access gates; direct Java erase/reset/counter calls also require `--allow-destructive`. `constants` is offline. Both guide methods continue to produce the same W-21 command. The six-digit profile regex is exposed as a constant but is not used to reject wider numbers: the master does not enforce that regex in its builder method.

For original-name Python use:

```python
from uart_command_builder import UARTCommandBuilder, DistanceUOM

builder = UARTCommandBuilder()
print(builder.prepareSetDistanceUOM(DistanceUOM.METERS))
print(builder.prepareSendFlightWarningsCommand(["1000", "2000", "3000"]))
print(builder.prepareSendFlightWarningsCommand(2, ["1000", "2000", "3000", "4000"]))
assert builder.prepareSendFreeFallSoundSetupCommand(0, 1) is None
assert UARTCommandBuilder.INSTANCE.prepareGetDeviceInfoCommand() == "Who?"
```

All 38 original camelCase names also exist on `JumpTrack` as async transport methods, and `await device.execute_java(method_name, *arguments)` is equivalent. These methods return raw device responses after sending, rather than builder strings. Configuration/destructive permissions must be enabled on the device object as before.

The master contains no profile decoder, altitude/pressure conversion, unit-bearing response parser, checksum verification or Bluetooth transport. The experimental plotting code and observed response parsers are extensions, not claims of Java-master functionality. Android/Kotlin compiler metadata and generated switch tables are represented by the Python enums/manifest; Android Crashlytics error messages use Python logging. Python exceptions adapt Java type/parse errors to `TypeError` / `ValueError`. Java's default-locale number formatting is represented using ASCII decimal output; Calendar is adapted to Python datetime fields, not a full Android Calendar implementation (e.g. BC dates are outside datetime's range).

## Setup and quick start

From the project directory:

```bash
git clone https://github.com/emoninet2/lb-jumptrack-python.git
cd lb-jumptrack-python
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export JUMPTRACK_ADDRESS="YOUR_DEVICE_ADDRESS"
.venv/bin/python jumptrack.py --help
```

Dependencies are installed from requirements.txt. Set your own Bluetooth device identifier with `--address`, `JUMPTRACK_ADDRESS`, or an ignored local `.jumptrack-address` file. Enable Bluetooth on both the computer and the device before a live command.

Examples below use the shorthand `jt`. Define it in your current Bash session:

```bash
jt() { .venv/bin/python jumptrack.py "$@"; }
```

```bash
jt                         # Read device info, jump counter and jump list
jt --settings              # Also read warnings, speed units and R-40/R-41/R-42
jt --beeps off             # Disable button beeps, preserving other W-40 fields
jt beeps on                # Enable button beeps; equivalent subcommand syntax
jt --dry-run set-sound canopy 3 6
jt acc --help
```

The final preview command prints `W-08-00000-00000-00003-00006` without opening Bluetooth.

## Command structure and global options

```text
jt [GLOBAL OPTIONS] COMMAND [COMMAND OPTIONS]
```

Put global options **before** the command. Run a single command per invocation. Explicit commands run only that operation; they do not also download the logbook.

| Global option | Meaning |
| --- | --- |
| `--address ADDRESS` | Set the BLE identifier; no personal device address is bundled. |
| `--debug` | Print received packets as hex. |
| `--dry-run` | Preview a subcommand with no Bluetooth connection or file writes. Works for destructive commands without enabling them. |
| `--output FILE` | Save a successful subcommand's raw response or status text; creates parent directories and overwrites that file. |
| `--allow-destructive` | Enable an explicitly selected erase, factory reset, or jump-counter replacement command. |
| `--help` | Show command list. `COMMAND --help` shows its arguments. |

```bash
jt --address YOUR_DEVICE_ADDRESS --debug info
jt --output jumptrack_data/settings_40.txt settings-40
jt --dry-run erase-logbook
```

A configuration subcommand itself requests a write; it needs no additional write-enable flag. The three destructive commands retain the separate flag shown below. Dry-run of `beeps` displays the read/change/read sequence rather than inventing current settings.

## Read commands

| Command / example | Result |
| --- | --- |
| `jt info` | Device information (`Who?`). |
| `jt jump-counter` | Jump counter. |
| `jt jump-list` | Jump list. |
| `jt warnings` | All warning records (`R-00`), raw response. |
| `jt speed-unit` | Speed unit (`R-38`), raw response. |
| `jt settings-40` | BLE mode, button beeps, dive type, temperature unit (`R-40`). |
| `jt settings-41` | Tap-to-enable-BLE and flat-line settings (`R-41`). |
| `jt settings-42` | Display settings (`R-42`). |
| `jt profile 35` | Hex profile for jump 35. |
| `jt profile 35 --timeout 120` | Profile with a 120-second response timeout. |
| `jt acc 35 0 60` | Hex ACC data for jump 35, start 0, duration 60. |
| `jt acc 35 0 60 --format text --timeout 120` | Text ACC data with a 120-second timeout. |

Profile and ACC timeouts default to 90 seconds; overrides accept 1–3600. Jump numbers and ACC start/duration fields accept the signed Java int domain. Their widths (five digits for jumps, three for ACC times) are minimums. Their exact firmware interpretation is not established by the builder source.

`warnings` prints raw records. Use the legacy `--warnings` flag below to also generate the existing human-readable and JSON summaries.

## Button beeps and device settings

```bash
jt beeps off
jt beeps on
```

The beep shortcut reads R-40, changes only its beep field, writes W-40, then reads R-40 again to verify all four values. It makes no write when already set. It refuses unknown, ambiguous, or incomplete response layouts. The expected response layout is one `W-40-xxxxx-xxxxx-xxxxx-xxxxx` record followed by EOF; the live PROTRACK 3 read confirmed this layout. The write and readback sequence remains untested on hardware.

The following commands **replace the entire settings group**. All named fields are required so omitted settings are never silently assigned defaults:

```bash
jt set-settings-40 --ble-mode automatic --beeps off --dive-type default --temperature-unit celsius
jt set-settings-41 --tap-to-enable-ble on --flat-line off
jt set-settings-42 --backlight-value 50 --date-format eu --show-time-under-canopy on --lcd-timeout 30
```

| Command | Accepted settings |
| --- | --- |
| `set-settings-40` | `--ble-mode automatic/economy`; `--beeps on/off`; `--dive-type default/3_seconds/slow/super_slow`; `--temperature-unit celsius/fahrenheit`. |
| `set-settings-41` | `--tap-to-enable-ble on/off`; `--flat-line on/off`. Two reserved fields are written as zero, matching Java. |
| `set-settings-42` | `--backlight-value INT`; `--date-format eu/us`; `--show-time-under-canopy on/off`; `--lcd-timeout INT`. |

Read `settings-40`, `settings-41`, or `settings-42` first to inspect existing values. Only the beep shortcut performs automatic readback verification. INT fields accept the signed Java int domain; Java sets no narrower bounds here. This is not a guarantee that every value is meaningful to every model.

## Units, time and altitude

```bash
jt set-distance-unit feet
jt set-distance-unit meters
jt set-speed-unit mph
jt set-speed-unit kmh
jt set-datetime now
jt set-datetime 2026-10-18T14:30:00
jt set-freefall-time 12 34 56
jt set-altitude 500
jt set-altitude 500 --negative
```

Datetime uses local wall-clock values; `now` uses your computer's current local time. Explicit datetimes must omit a timezone offset. Total freefall time takes hours, minutes and seconds; each accepts a signed Java int, without normalization. Altitude takes a magnitude of 0–65000; `--negative` selects the negative sign.

## Warning banks and sound

```bash
jt set-warnings freefall 4500 3500 2500 --bank 1
jt set-warnings canopy 1500 1000 500 --bank 2
jt set-warnings flight 1000 2000 3000 4000 --bank 3
jt set-warnings flight 1000 2000 3000
jt set-active-bank freefall 1
jt set-active-bank canopy 2
jt set-active-bank flight 3
jt set-sound freefall 3 6
jt set-sound canopy 4 7
jt set-sound flight 2 5
jt play-sound freefall
jt play-sound canopy
jt play-sound flight
jt default-alarms
```

Warning categories are `freefall`, `canopy`, and `flight`. Supply numeric strings. Exactly four values produce four fields; any other valid length of at least three gets a leading zero and uses only the first three values. Used values are parsed as signed Java ints; negative signs are rejected by the numeric-list check. Banks are 1–4. `--bank` is required for freefall/canopy. Flight without a bank uses legacy W-01; banked flight uses W-33 through W-36.

Altitude values are transmitted as supplied. Units and the meaning of zero thresholds are not inferred. Read the device configuration before choosing values. Sound pitch is 1–7 and volume is 1–10; these apply to the category, rather than individual thresholds. `play-sound` triggers audio. `default-alarms` restores factory warning values.

## Backlight, motion, guides and power

```bash
jt backlight on --value 50
jt backlight off
jt motion-alarm 10 5
jt swoop-guide on
jt swoop-guide off
jt track-guide on
jt track-guide off
jt power-off
```

Backlight value accepts a signed Java int (default 0; formatted to a minimum of two digits) and is ignored when switching off. Motion takes signed Java int countdown and sensitivity, formatted to a minimum of three digits; units/ranges meaningful to firmware remain unverified. Both guide names deliberately produce the same W-21 command, matching the supplied Java. Power-off can disconnect the device before the client's expected response terminator arrives.

## Logbook and factory operations

These examples perform destructive changes when run against a connected device:

```bash
jt --allow-destructive set-jump-counter 35
jt --allow-destructive erase-logbook
jt --allow-destructive factory-reset
```

Jump-counter replacement accepts a signed Java int, formatted to a minimum of five digits. Preview any operation first with `--dry-run` if you want to inspect its UART command without a connection. Commands are never retried automatically.

## Existing flag-based usage and saved files

These remain supported:

```bash
jt --list-devices
jt --warnings
jt --settings
jt --profile 35
jt --settings --profile 35
jt --beeps off
```

Without a subcommand, normal reads save responses in `jumptrack_data/` relative to your working directory. Existing filenames are overwritten. `--warnings` / `--settings` also write parsed warning summaries where the response can be recognized. `--beeps` alone changes only beeps. It can be combined with legacy read flags to change beeps before performing those reads.

Do not combine a subcommand with legacy read flags, `--beeps`, or `--list-devices`. For example, use `jt warnings` or `jt --warnings` separately. `--dry-run`, `--output`, and `--allow-destructive` require a subcommand.

## Responses, compatibility and troubleshooting

The client expects responses ending in `EOF\r\n`. Most subcommands print raw responses; profile/ACC decoding and checksums are not supplied by the Java builder. Beep-only updates additionally perform the readback described above. Other write responses are not proof that firmware applied the requested change.

If a write times out or the device disconnects, it may already have applied. Inspect the device or read its settings before deciding what to do next. Power-off, reset and sound commands have not been verified to use the same response framing. An unfamiliar R-40 response will stop the beep shortcut before changing settings.

Supported family names inherited from the existing code are PROTRACK, STELLA, ORDINAL and VISOX. The existing verified-model list contains PROTRACK 3; this does not establish that every command works on other families. CLI expansion was tested offline with mocked BLE clients, without connecting to a device.

Subcommand argument errors exit with code 2; handled connection/response/verification failures exit with code 1. Legacy batch reads retain the original behavior of printing timeout warnings and continuing to the next read. Run `--debug` before a command to inspect received packets.

## Python API and offline tests

```python
from uart_command_builder import UARTCommandBuilder
from jumptrack import JumpTrack

builder = UARTCommandBuilder()
print(builder.set_sound("canopy", 3, 6))  # No Bluetooth dependency in builder

# Inside an async function:
# device = JumpTrack(address="...", allow_writes=True)
# try:
#     await device.connect()
#     print(await device.set_button_beeps(False))
# finally:
#     await device.disconnect()
```

All builder methods have asynchronous client counterparts. The client also has `set_button_beeps()` and warning-summary helpers. Client configuration writes require `allow_writes=True`; destructive methods require `allow_destructive=True`.

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

The tests cover all 40 public Java method signatures, all builder-to-CLI routes, argument validation, offline previews, destructive gates, mocked dispatch, output files, response fragments, timeouts, and beep preservation/verification. They do not need Bluetooth.

## Live test results

A read-only PROTRACK 3 firmware 01.04 test confirmed device information, jump counter/list, all-warning reads, R-40/R-41 records, and retrieval of jump 35’s hex profile. Button beeps read as off. No write commands were sent.

Standalone R-38 returned only a blank line and timed out; speed settings were present inside R-00 instead. R-42 returned a complete response without a W-42 record. Both ACC formats returned complete responses with no samples for jump 35/start 0/duration 5; data retrieval is not yet verified. See docs/LIVE_TEST_RESULTS.md for details. All configuration writes, reset/erase, sound playback and power-off remain untested.

## Manual profile plotting test

`plot_profile.py` reads one profile and plots raw 16-bit words. It defaults to no device writes and never runs Bluetooth when imported by a test runner. Matplotlib is installed in the existing virtual environment.

```bash
# Plot the profile already downloaded, without Bluetooth:
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt

# With device Bluetooth enabled, download and plot a single jump:
.venv/bin/python plot_profile.py --jump 35

# Optional interactive plot window (requires a working GUI backend):
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --show
```

Outputs are PNG, CSV, original response text and header/checksum metadata JSON under `jumptrack_data/profile_plots/`. Use `--output-dir PATH` to choose another folder. Matching output filenames are overwritten, but the input file itself is not rewritten.

The decoder supports the layout observed on PROTRACK 3 firmware 01.04: 16 decimal header fields followed by groups of four hex digits. Units, the meanings of most header fields, checksums and the sample interval remain unverified. Default axes are raw value against sample index, not altitude against time. `--sample-interval SECONDS` changes the horizontal axis only when you supply a known sample interval. The saved jump 35 response yields 1,216 raw words.

Offline decoder checks: `.venv/bin/python -m unittest tests.test_profile_parser -v`.

The latest full suite has 45 passing test functions covering all 40 Java signatures, including an independent Java execution comparison for 663 inputs. The Java oracle test requires `javac` and `java` and skips if a JDK is absent. It compiles only a temporary generated harness, leaving the master file untouched.

## Raw data and estimated units

The device's profile decoder is still unconfirmed. The plotting tool now supports explicitly assumed pressure and estimated height in feet/meters, while retaining raw values in its chart and CSV:

```bash
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --pressure-scale 0.1 --reference-pressure 1007 --units feet
```

The 0.1 hPa/count scale and 1007 hPa reference are assumptions for this example. The estimated height decreases during descent but is not confirmed device altitude. No Bluetooth connection is used with `--file`. See [profile format and conversion assumptions](docs/PROFILE_FORMAT.md) for the model, limitations, API, CSV fields, and live-read usage.

## Project layout

```text
UARTCommandBuilder.java        Java master, unchanged
jumptrack.py                   BLE client and CLI entry point
jumptrack_cli.py               CLI commands and argument routing
java_uart_command_builder.py   Java-master behavior and original names
uart_command_builder.py        Python-friendly builder aliases
plot_profile.py                Read/plot raw profiles and experimental units
requirements.txt               Python dependencies
README.md                      Setup and command reference
tests/                         Offline regression tests (no real device)
docs/                          Java audit, manifest, live results, profile notes
jumptrack_data/                 Preserved device downloads and generated plots
archive/                       Recoverable legacy scripts and scratch backups
.venv/                         Existing Python environment
```

`plot_profile.py` replaces the earlier manual script named `test_profile_plot.py`. Test files are now under `tests/`; run `.venv/bin/python -m unittest discover -s tests -t . -v` from this folder. The count of test functions is independent of the 40 Java signatures: several tests loop over all signatures and all 663 parity inputs. Old scripts were archived, not discarded. The Java master and source device downloads were preserved; generated bytecode caches were removed.

## Using the profile count

The API now exposes `profile_count_field` in parsed jump-list rows. `unknown_1` remains an alias for compatibility; `unknown_2` is unchanged. This field matches the final profile header field in all three tested jumps. The exact inclusive counting convention remains unverified.

`parse_profile()` reports `profile_count_field`, `decoded_word_count`, `count_difference`, `count_matches_observed_layout`, and `validation_warnings`. The observed firmware rule is header count = decoded words + 1. A mismatch warns about possible missing/extra data or a different layout; it is not proof of corruption. This is a structural check, not a checksum verification.

```bash
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --strict-count --expected-count 1217
```

`--expected-count` optionally cross-checks the jump-list field against the profile header. `--strict-count` refuses to plot/export when either check fails; otherwise mismatches generate warnings and are stored in metadata JSON. No samples are invented, removed or padded. The field does not establish the sample interval, altitude units, or duration.

## Reference source and licensing status

This is an unofficial project, not affiliated with or endorsed by LB Altimeters. The implementation was developed by examining an extracted Android UART command builder. The extracted `UARTCommandBuilder.java` is kept local and is not distributed in this repository. The public signature manifest and ordinary offline tests are included. Tests that compile or hash-check the actual Java reference skip when the local reference is absent.

No open-source license is granted by this repository at present. Redistribution/relicensing rights for translated material have not been established; do not assume the Python translation is MIT-licensed. Excluding the original Java file does not itself resolve those rights.
