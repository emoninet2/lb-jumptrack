# JumpTrack Python

Unofficial BLE UART client based on an extracted Android `UARTCommandBuilder.java`.
It provides grouped CLI commands, a Python API, and an experimental profile plotter.
PROTRACK 3 is the tested model; support for other device families is unverified.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export JUMPTRACK_ADDRESS="YOUR_DEVICE_ADDRESS"
jt() { .venv/bin/python jumptrack.py "$@"; }
jt --help
jt tree
```

Alternatively, use `--address` or put your identifier in the ignored local
`.jumptrack-address` file. Enable Bluetooth on the device immediately before a
live request. Constants, help, the command tree and dry runs need no connection.

## CLI

Commands are grouped by purpose. Run `--help` at any level for arguments and
choices. Entering a group alone shows its help. See the [full tree](docs/CLI_TREE.md).

| Group | Purpose | Example |
| --- | --- | --- |
| `device` | Information, recognized models and power | `jt device info` |
| `logbook` | Jump list, profiles, ACC and accumulated totals | `jt logbook profile 35` |
| `settings` | Device preferences and units | `jt settings beeps off` |
| `alarms` | Warning banks, sounds, motion and guides | `jt alarms sound canopy play` |
| `maintenance` | Logbook erasure and factory reset | `jt --allow-destructive maintenance erase-logbook` |
| `advanced` | Java methods, constants and complete settings records | `jt advanced raw-settings get 40` |
| `tree` | Offline command hierarchy | `jt tree` |

Put shared options **before** the first command:

| Option | Purpose |
| --- | --- |
| `--address IDENTIFIER` | Override the configured BLE identifier. |
| `--debug` | Print incoming BLE packets as hex. |
| `--dry-run` | Preview a device operation without connecting or writing files. |
| `--output FILE` | Save the operation's displayed result; overwrite an existing file. |
| `--allow-destructive` | Permit erase, factory reset or jump-counter replacement. |

```bash
jt --address YOUR_DEVICE_ADDRESS device info
jt --output jumptrack_data/profile.txt logbook profile 35 --timeout 120
jt --dry-run alarms sound canopy set 3 6
jt device list-models
```

Without a command, the legacy default reads device information, jump counter and
jump list and saves them under `jumptrack_data/` in the current directory.

### Logbook

```bash
jt logbook list
jt logbook profile 35
jt logbook acc 35 0 60 --format hex --timeout 120
jt logbook totals jumps get
jt --allow-destructive logbook totals jumps set 35
jt logbook totals freefall-time set 12 34 56
```

Profile and ACC response timeouts default to 90 seconds; overrides accept
1–3600 seconds. Jump numbers, ACC fields and total freefall-time fields accept
signed Java integers. Their exact firmware limits and ACC interpretation remain
unverified. The freefall-time command replaces the accumulated total.

### Settings

```bash
jt settings show
jt settings beeps off
jt settings dive-type
jt settings dive-type slow
jt settings units distance feet
jt settings units speed kmh
jt settings units show-speed
jt settings units temperature celsius
jt settings datetime now
jt settings datetime 2026-10-18T14:30:00
jt settings altitude 500 --negative
jt settings bluetooth mode economy
jt settings bluetooth tap-to-enable on
jt settings display backlight on --value 50
jt settings display date-format eu
jt settings display show-time-under-canopy on
jt settings display timeout 30
jt settings flat-line off
```

`settings show` labels known fields and retains raw responses. Unknown values
remain explicitly unknown. A missing W-42 record is reported rather than filled
with invented values. `settings dive-type` reads the current dive type; supplying
a value changes it:

| Code | Java-derived enum | CLI value |
| --- | --- | --- |
| 0 | `DEFAULT` | `default` |
| 1 | `_3_SECONDS` | `3_seconds` |
| 2 | `SLOW` | `slow` |
| 3 | `SUPER_SLOW` | `super_slow` |

“None” has not been verified as a device-display alias of `DEFAULT`.

Individual controls in settings groups 40–42 read the current record, preserve
other fields, skip unchanged values, write once and read back for verification.
Malformed, incomplete, ambiguous or unknown records prevent a write. Operations
using the same client serialize these updates and complete-group writes. These
write sequences are tested with mocks; live configuration writes remain unverified.
Dry runs show the planned sequence because current fields require a live read.

Datetime accepts local wall-clock values without a timezone offset. Altitude
accepts magnitude 0–65000; `--negative` selects the negative sign. Units and
firmware limits for display timeout/backlight values are not established by the
builder. Individual numeric settings accept nonnegative signed Java integers;
the advanced complete-group interface preserves the broader Java input domain.

TAS/SAS is currently unsupported. Comparing TAS and SAS reads across `R-00`–`R-99`
found no mode-dependent field. This does not prove the hardware cannot expose it.
See [hardware observations](docs/PROTOCOL_OBSERVATIONS.md).

### Alarms and maintenance

```bash
jt alarms show
jt alarms warnings freefall set 4500 3500 2500 --bank 1
jt alarms warnings canopy select-bank 2
jt alarms warnings flight set 1000 2000 3000
jt alarms sound canopy set 4 7
jt alarms sound canopy play
jt alarms motion 10 5
jt alarms swoop-guide on
jt alarms track-guide off
jt alarms restore-defaults
jt device power-off
jt --allow-destructive maintenance erase-logbook
jt --allow-destructive maintenance factory-reset
```

Warning banks are 1–4. Freefall/canopy warning writes require `--bank`; flight can
omit it for the legacy W-01 command. Exactly four warning values produce four
fields; other valid lengths of at least three produce a leading zero and the
first three values. Numeric-list validation rejects signed strings. Threshold
units and the meaning of zero are not inferred. Pitch is 1–7 and volume is 1–10.

Both guide commands produce the same W-21 write, matching the Java reference.
Motion countdown/sensitivity and backlight firmware limits remain unverified.
Power-off submits its write without waiting for EOF, as confirmed by a user test.
Other successful write responses do not by themselves confirm device behavior.
Commands are not retried automatically. After a write timeout, inspect the device
or read its settings before deciding whether to retry.

### Advanced commands and compatibility

```bash
jt advanced constants
jt --dry-run advanced java prepareSetDistanceUOM '["METERS"]'
jt --dry-run advanced java prepareSendFlightWarningsCommand '[2,["1000","2000","3000","4000"]]'
jt advanced raw-settings get 40
jt advanced raw-settings set 40 --ble-mode automatic --beeps off --dive-type default --temperature-unit celsius
jt advanced raw-settings set 41 --tap-to-enable-ble on --flat-line off
jt advanced raw-settings set 42 --backlight-value 50 --date-format eu --show-time-under-canopy on --lcd-timeout 30
```

Complete-group writes require all named fields and replace the entire record.
W-41 reserved fields are set to zero. These advanced writes do not automatically
preserve or verify current settings. Use individual controls for that behavior.
Java enum arguments use exact member names; arguments are a JSON array. Both
freefall-time and flight-warning overloads are supported. See the
[Java parity reference](docs/JAVA_MASTER_PARITY.md) for all signatures and rules.

Original flat commands and operation flags remain accepted for existing scripts
but are hidden from the main help/tree. Examples: `jt beeps off`, `jt profile 35`,
`jt --settings`, `jt --warnings`, `jt --profile 35`, `jt --list-devices`.
Do not mix a grouped/flat command with legacy operation flags. Legacy reads
write raw results and warning summaries to `jumptrack_data/`; matching filenames
are overwritten. Grouped commands print their result and save it only with
`--output`. Legacy batch reads report response timeouts and continue.

## Profile plotting

```bash
# Offline: use an existing download.
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt
# Live: download one profile, with configuration writes disabled.
.venv/bin/python plot_profile.py --jump 35
# Explicit, experimental pressure/height assumptions.
.venv/bin/python plot_profile.py --file jumptrack_data/jump_00035_profile.txt --pressure-scale 0.1 --reference-pressure 1007 --units feet
```

The plotter preserves raw words, header fields and checksum metadata. It exports
PNG, CSV, original response text and metadata JSON to `jumptrack_data/profile_plots/`.
Existing matching output files are overwritten; the source input is preserved.
Use `--show` for a GUI window, `--output-dir` to choose a destination, and
`--sample-interval` only when the actual interval is known.

Profile encoding, sample timing, checksums and physical units remain unverified.
Pressure conversion requires explicit assumptions. Structural count checks can
warn or fail with `--strict-count`; `--expected-count` compares against the
jump-list count field. See [profile format](docs/PROFILE_FORMAT.md) and
[count evidence](docs/PROFILE_COUNT_COMPARISON.md).

## Python API and verification

```python
from uart_command_builder import UARTCommandBuilder
from jumptrack import JumpTrack

print(UARTCommandBuilder().set_sound("canopy", 3, 6))
# Inside an async function:
# device = JumpTrack(address="...", allow_writes=True)
# try:
#     await device.connect()
#     print(await device.set_setting_field(40, 2, 2))
# finally:
#     await device.disconnect()
```

The builder exposes all 40 saved Java signatures (38 unique names), constants,
enum mappings, validation and null behavior. CamelCase client methods and
`execute_java()` expose the corresponding transports. Friendly adapters delegate
to the same builder. Java minimum formatting widths do not imply firmware bounds.

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

Tests mock Bluetooth and cover routing, permissions, settings preservation,
verification, transport framing, timeouts and experimental profile parsing.
Tests that hash or execute the private Java reference skip when it is absent;
execution also requires `javac` and `java`. Saved signatures allow ordinary
coverage to run without that source. See the parity reference for the historical
663-case Java comparison; skipped tests are not current execution evidence.

## Project files

| File | Purpose |
| --- | --- |
| `jumptrack.py` | BLE transport, response interpretation and CLI entry point |
| `jumptrack_cli.py` | Command definitions, grouping, routing and previews |
| `java_uart_command_builder.py` | Java-derived commands and JSON adapters |
| `uart_command_builder.py` | Compatible Python-friendly builder aliases |
| `plot_profile.py` | Experimental profile parsing, conversion and plotting |
| `tests/` | Offline regression tests and saved Java signatures |
| `docs/` | Command tree, protocol observations and technical references |
| `jumptrack_data/` | Ignored local captures, plots and investigation scripts |

## Reference source and licensing status

This project is unofficial and is not affiliated with or endorsed by LB Altimeters.
The extracted `UARTCommandBuilder.java` is a private, optional reference and is not
distributed. It is absent from this checkout. Public signatures and ordinary tests
are included. The builder contains no response decoder, checksum verification or
Bluetooth transport; those parts of this project are separate implementations.

No open-source license is granted by this repository at present. Redistribution
and relicensing rights for translated material have not been established; do not
assume the Python translation is MIT-licensed. Excluding the Java reference does
not itself resolve those rights.
