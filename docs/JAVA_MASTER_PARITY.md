# Java master parity audit

This records the historical audit against the private `UARTCommandBuilder.java` reference. The reference is not distributed and is absent from this checkout. Current tests use saved signatures; source-hash and Java-execution checks skip without it. The audit did not modify the source.

SHA-256 before and after this audit:

`b68c90a5d30d2dc536a352fcb8c584f83fb4117519c6d0d2fac4a597358e76f5`

## Result

All 40 public Java method signatures (38 unique names) and eight scalar constants are implemented in Python and exposed through the CLI. The earlier port covered ordinary command strings but diverged on validation and formatting; those divergences have now been corrected. This report replaces the earlier claim that typical golden cases alone established full parity.

- `java_uart_command_builder.py`: original method names, both overload pairs, type adapters, enum branches, Java null results, numeric parsing and logging behavior.
- `uart_command_builder.py`: original API inherited plus existing Python-friendly names, all delegating to the Java-master implementation.
- `jumptrack.py`: asynchronous original-name methods and `execute_java`, with access gates; no null command is sent.
- `jumptrack_cli.py`: existing friendly commands plus `java METHOD JSON_ARRAY` for every original signature, and offline `constants`.
- `tests/test_java_master_parity.py`: independent execution of extracted original Java method bodies, with generated Android/Kotlin dependency stubs, against 663 cases.
- `tests/test_java_cli.py`: coverage of all original signatures and the same 663 cases through JSON CLI adaptation, plus transport/null/access tests.

No Bluetooth connection, configuration change, reset, or deletion was performed during this audit.

## Important corrections

Java widths are minimums; arbitrary 2/3/5/6-digit Python limits were removed. Signed Java int inputs are allowed where Java applies no explicit constraint. Null returns are preserved. Warning lists longer than four validate all strings but format only their first three values with a leading zero. Total freefall time supports exactly the three-int and three-string overloads; string parsing accepts signs and BMP decimal digits, rejects whitespace and overflow. The altitude method exposes its original numeric sign argument and 64-bit magnitude input, then applies Java's explicit 0–65000 validity rule. Unsupported speed enums raise `Wrong UOM`. Both guide methods remain identical W-21 commands.

The public profile regex remains a constant; it is not enforced by the Java profile-building method. MAX_VALUES_NUMBER=4 is retained even though the Java list method accepts longer lists. No Java behavior has been silently rewritten to follow those constants instead of the actual method bodies.

## Verification and limits

At the time of that audit, 41 test functions passed after adding profile conversion tests. All 40 Java signatures are still covered. The independent Java oracle compared 663 cases spanning every overload, enums, booleans, boundaries, negatives, oversized formatted fields, null inputs/results, bad lists, Unicode numeric strings and parse errors. All matched. The same 663 input cases pass through the JSON CLI adapter with matching results/errors.

The original source is decompiled Android/Kotlin code and cannot compile standalone. The test extracts its actual method bodies and generated enum-switch mapping into a temporary Java class, stubs missing runtime helpers, and repairs only the decompiler artifact `Iterator<T>` to `Iterator<?>`. Helper stubs mimic StringUtils numeric validation, null checks and the documented format constant; the oracle validates the command logic, not the full Android runtime. Java output uses Locale.US for ASCII comparison. Python maps Calendar to datetime, Java exceptions to TypeError/ValueError, and Crashlytics to logging. External enum classes were not supplied: their referenced names/branches are represented, and DateFormat.US represents the non-EU branch. Compiler metadata, StabilityInferred markers and synthetic constructor markers have no separate command behavior to expose.

The master does **not** contain profile decoding, altitude/pressure conversion, checksum logic, response interpretation or transport. Those cannot be copied from this file. Existing experimental parsers and the profile plot remain clearly labeled extensions. No firmware-write compatibility claim follows from offline parity.

## CLI usage

```bash
.venv/bin/python jumptrack.py constants
.venv/bin/python jumptrack.py --dry-run java prepareGetDeviceInfoCommand
.venv/bin/python jumptrack.py --dry-run java prepareSendFlightWarningsCommand '[["1000","2000","3000"]]'
.venv/bin/python jumptrack.py --dry-run java prepareSendFlightWarningsCommand '[2,["1000","2000","3000","4000"]]'
.venv/bin/python jumptrack.py --dry-run java prepareSetTotalFreeFallTimeCommand '["+100000","-2","03"]'
.venv/bin/python jumptrack.py --dry-run java prepareSendAltitudeCommand '[500,-1]'
```

For live direct methods, omit --dry-run. Erase/reset/counter replacements still require --allow-destructive before `java`. A null builder result prints `null` in dry-run and aborts before connecting in live mode. Normal read/configuration aliases remain available.

## Complete mapping

Each row is a public method signature from the master. The direct CLI form is `java METHOD JSON_ARRAY`; the last column shows its friendly CLI equivalent.

| Master signature | Original Python API / direct CLI method | Friendly CLI example |
| --- | --- | --- |
| `prepareDateTimeCommand(Calendar calendar)` | `prepareDateTimeCommand` | `set-datetime 2026-10-18T14:07:09` |
| `preparePowerOffCommand()` | `preparePowerOffCommand` | `power-off` |
| `prepareSetDistanceUOM(DistanceUOM measureSystem)` | `prepareSetDistanceUOM` | `set-distance-unit meters` |
| `prepareSetSpeedUOM(SpeedUOM measureSystem)` | `prepareSetSpeedUOM` | `set-speed-unit kmh` |
| `prepareGetSpeedUOM()` | `prepareGetSpeedUOM` | `speed-unit` |
| `prepareSetTotalFreeFallTimeCommand(String hoursString, String minutesString, String secondsString)` | `prepareSetTotalFreeFallTimeCommand` | `set-freefall-time 12 3 4` |
| `prepareSetTotalFreeFallTimeCommand(int hours, int minutes, int seconds)` | `prepareSetTotalFreeFallTimeCommand` | `set-freefall-time 12 3 4` |
| `prepareSendFlightWarningsCommand(List<String> warnings)` | `prepareSendFlightWarningsCommand` | `set-warnings flight 1000 2000 3000` |
| `prepareSendFreeFallWarningsCommand(int bank, List<String> warnings)` | `prepareSendFreeFallWarningsCommand` | `set-warnings freefall 1000 2000 3000 4000 --bank 4` |
| `prepareSendFlightWarningsCommand(int bank, List<String> warnings)` | `prepareSendFlightWarningsCommand` | `set-warnings flight 1000 2000 3000 4000 --bank 4` |
| `prepareSendCanopyWarningsCommand(int bank, List<String> warnings)` | `prepareSendCanopyWarningsCommand` | `set-warnings canopy 1000 2000 3000 --bank 4` |
| `prepareSendFreeFallSoundSetupCommand(int pitch, int volume)` | `prepareSendFreeFallSoundSetupCommand` | `set-sound freefall 7 10` |
| `prepareSendCanopySoundSetupCommand(int pitch, int volume)` | `prepareSendCanopySoundSetupCommand` | `set-sound canopy 1 1` |
| `prepareSendFlightWarningsSoundSetupCommand(int pitch, int volume)` | `prepareSendFlightWarningsSoundSetupCommand` | `set-sound flight 3 8` |
| `prepareSendFreeFallPlaySoundCommand()` | `prepareSendFreeFallPlaySoundCommand` | `play-sound freefall` |
| `prepareSendCanopyPlaySoundCommand()` | `prepareSendCanopyPlaySoundCommand` | `play-sound canopy` |
| `prepareSendFlightAlarmsPlaySoundCommand()` | `prepareSendFlightAlarmsPlaySoundCommand` | `play-sound flight` |
| `prepareSetDefaultAlarmValuesCommand()` | `prepareSetDefaultAlarmValuesCommand` | `default-alarms` |
| `prepareFactoryResetCommand()` | `prepareFactoryResetCommand` | `factory-reset` |
| `prepareReadDeviceSettingsR40Command()` | `prepareReadDeviceSettingsR40Command` | `settings-40` |
| `prepareReadDeviceSettingsR41Command()` | `prepareReadDeviceSettingsR41Command` | `settings-41` |
| `prepareReadDeviceSettingsR42Command()` | `prepareReadDeviceSettingsR42Command` | `settings-42` |
| `prepareDeviceSettingsW40Command(DeviceBLEMode mode, boolean beeps, DeviceDiveType diveType, DeviceTemperatureUnits temperatureUnits)` | `prepareDeviceSettingsW40Command` | `set-settings-40 --ble-mode economy --beeps on --dive-type super_slow --temperature-unit fahrenheit` |
| `prepareWriteDeviceSettingsW41Command(boolean tapToEnableBLE, boolean flatLine)` | `prepareWriteDeviceSettingsW41Command` | `set-settings-41 --tap-to-enable-ble on --flat-line off` |
| `prepareDeviceSettingsW42Command(int backlightValue, DateFormat dateTime, boolean showTimeUnderCanopy, int lcdTimeOut)` | `prepareDeviceSettingsW42Command` | `set-settings-42 --backlight-value 75 --date-format us --show-time-under-canopy on --lcd-timeout 30` |
| `prepareBacklightCommand(boolean backlight, int backlightValue)` | `prepareBacklightCommand` | `backlight on --value 5` |
| `prepareMotionAlarmCommand(int countdown, int sensitivity)` | `prepareMotionAlarmCommand` | `motion-alarm 5 12` |
| `prepareSetSwoopGuideCommand(boolean checked)` | `prepareSetSwoopGuideCommand` | `swoop-guide on` |
| `prepareSetTrackGuideCommand(boolean checked)` | `prepareSetTrackGuideCommand` | `track-guide off` |
| `prepareSetCanopyActiveBankCommand(int bankIndex)` | `prepareSetCanopyActiveBankCommand` | `set-active-bank canopy 1` |
| `prepareSetFlightWarningActiveBankCommand(int bankIndex)` | `prepareSetFlightWarningActiveBankCommand` | `set-active-bank flight 2` |
| `prepareSetFreeFallActiveBankCommand(int bankIndex)` | `prepareSetFreeFallActiveBankCommand` | `set-active-bank freefall 3` |
| `prepareSendAltitudeCommand(long altitude, int sign)` | `prepareSendAltitudeCommand` | `set-altitude 65000 --negative` |
| `prepareReadJumpCountCommand()` | `prepareReadJumpCountCommand` | `jump-counter` |
| `prepareSetJumpCountCommand(int count)` | `prepareSetJumpCountCommand` | `set-jump-counter 35` |
| `prepareEraseEntireLogbookCommand()` | `prepareEraseEntireLogbookCommand` | `erase-logbook` |
| `prepareGetACCCommand(int jumpNumberArg, int startTime, int durationArg)` | `prepareGetACCCommand` | `acc 35 5 90 --format text` |
| `prepareGetACCCommandHex(int jumpNumberArg, int startTime, int durationArg)` | `prepareGetACCCommandHex` | `acc 35 5 90` |
| `prepareGetDeviceInfoCommand()` | `prepareGetDeviceInfoCommand` | `info` |
| `prepareLoadLumpProfileCommandHex(int jumpNumber)` | `prepareLoadLumpProfileCommandHex` | `profile 123456` |

## Constants

| Name | Value |
| --- | --- |
| `READ_ALL_WARNINGS_COMMAND` | `R-00` |
| `READ_JUMPS_LIST_COMMAND` | `Get New Jump List` |
| `READ_JUMP_COUNTER_COMMAND` | `Get Jump Counter` |
| `READ_JUMP_PROFILE_HEX_COMMAND` | `Get Hex Profile in Jump` |
| `READ_JUMP_PROFILE_HEX_COMMAND_PATTERN` | `Get Hex Profile in Jump \d{2,6}` |
| `MIN_VALUES_NUMBER` | `3` |
| `MAX_VALUES_NUMBER` | `4` |
| `$stable` | `0` |

`UARTCommandBuilder.INSTANCE` and `UARTCommandBuilder.Companion` are available. The private `isAllNumeric` behavior is implemented by the numeric-string helper and warning-list validation; generated enum switch mappings are represented by enums. It is not a public command.

## Public repository

The extracted Java master is excluded from distribution. Its signature data is checked in for ordinary offline tests. Java-source execution/hash tests run only when that reference is available locally. No open-source license is claimed for translated material.
