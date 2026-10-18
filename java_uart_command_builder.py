"""Source-faithful command construction from the untouched Java master.

The original camelCase names and null results are preserved (null -> None).
Java int/long limits are type limits; printf widths are minimum widths.
Enums below reproduce the names used by this file, not unknown Android enum
members or their original ordinals. datetime is the Python Calendar adapter.
No response decoding, checksum or profile-unit conversion exists in the master.
"""

import logging
import unicodedata
from datetime import datetime
from enum import Enum


class DistanceUOM(Enum):
    FEET = 0
    METERS = 1


class SpeedUOM(Enum):
    MILE_HOUR = 0
    KILOMETER_HOUR = 1
    FEET_SECONDS = 2
    METER_SECOND = 3


class DeviceBLEMode(Enum):
    AUTOMATIC = 0
    ECONOMY = 1


class DeviceDiveType(Enum):
    DEFAULT = 0
    _3_SECONDS = 1
    SLOW = 2
    SUPER_SLOW = 3


class DeviceTemperatureUnits(Enum):
    CELSIUS = 0
    FAHRENHEIT = 1


class DateFormat(Enum):
    EU = 0
    US = 1


CONSTANTS = {
    "READ_ALL_WARNINGS_COMMAND": "R-00",
    "READ_JUMPS_LIST_COMMAND": "Get New Jump List",
    "READ_JUMP_COUNTER_COMMAND": "Get Jump Counter",
    "READ_JUMP_PROFILE_HEX_COMMAND": "Get Hex Profile in Jump",
    "READ_JUMP_PROFILE_HEX_COMMAND_PATTERN": r"Get Hex Profile in Jump \d{2,6}",
    "MIN_VALUES_NUMBER": 3,
    "MAX_VALUES_NUMBER": 4,
    "$stable": 0,
}
globals().update(CONSTANTS)


def java_int(value, bits=32):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"Expected Java {'int' if bits == 32 else 'long'}, received {value!r}"
        )
    if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
        raise ValueError(f"Outside signed Java {bits}-bit range: {value}")
    return value


def _decimal_character(char):
    # Commons StringUtils.isNumeric iterates UTF-16 chars; astral Nd digits
    # appear as surrogates and fail Character.isDigit there.
    return ord(char) <= 0xFFFF and unicodedata.category(char) == "Nd"


def _numeric(value):
    return (
        isinstance(value, str) and bool(value) and all(map(_decimal_character, value))
    )


def parse_java_int(value):
    if not isinstance(value, str):
        raise TypeError("Expected a string for Integer.parseInt")
    digits = value[1:] if value.startswith(("+", "-")) else value
    if not _numeric(digits):
        raise ValueError(f"Invalid Java integer string: {value!r}")
    return java_int(int(value))


def _format(value, width=5, bits=32):
    return f"{java_int(value, bits):0{width}d}"


def _boolean(value):
    if not isinstance(value, bool):
        raise TypeError("Expected boolean")
    return "00001" if value else "00000"


def _enum(value, expected):
    if not isinstance(value, expected):
        raise TypeError(f"Expected {expected.__name__}, received {value!r}")
    return value.value


def _warning_command(code, warnings, bank=None):
    if warnings is None:
        raise TypeError("warnings must not be null")
    if not isinstance(warnings, (list, tuple)):
        raise TypeError("Expected List<String> warnings")
    if bank is not None:
        java_int(bank)
    if (
        len(warnings) < 3
        or not all(_numeric(item) for item in warnings)
        or (bank is not None and not 1 <= bank < 5)
    ):
        return None
    # Java validates ALL strings but parses only the first three unless size==4.
    parts = [_format(parse_java_int(item)) for item in warnings[:3]]
    if len(warnings) == 4:
        parts.append(_format(parse_java_int(warnings[3])))
    else:
        parts.insert(0, "00000")
    return f"W-{code:02d}-" + "-".join(parts)


def _sound(code, pitch, volume):
    java_int(pitch)
    java_int(volume)
    if not 1 <= pitch < 8 or not 1 <= volume < 11:
        return None
    return f"W-{code}-00000-00000-{pitch:05d}-{volume:05d}"


def _bank(code, bankIndex, label):
    java_int(bankIndex)
    if 1 <= bankIndex < 5:
        return f"W-{code}-00000-00000-00000-{bankIndex:05d}"
    logging.getLogger(__name__).error("Wrong %s active bank index:%s", label, bankIndex)
    return None


class JavaUARTCommandBuilder:
    def prepareDateTimeCommand(self, calendar):
        if not isinstance(calendar, datetime):
            raise TypeError("calendar must be a datetime (Calendar adapter)")
        return (
            f"W-18-{calendar.second:02d}0{calendar.minute:02d}-000{calendar.hour:02d}"
            f"-{calendar.day:02d}0{calendar.month:02d}-0{calendar.year:04d}"
        )

    def preparePowerOffCommand(self):
        return "W-20-00000-00000-00000-00001"

    def prepareSetDistanceUOM(self, measureSystem):
        return f"W-16-00000-00000-00000-{_enum(measureSystem, DistanceUOM):05d}"

    def prepareSetSpeedUOM(self, measureSystem):
        code = _enum(measureSystem, SpeedUOM)
        if code in (2, 3):
            raise ValueError("Wrong UOM")
        return f"W-38-00000-00000-00000-{code:05d}"

    def prepareGetSpeedUOM(self):
        return "R-38"

    def prepareSetTotalFreeFallTimeCommand(self, hours, minutes, seconds):
        values = (hours, minutes, seconds)
        if all(isinstance(value, str) for value in values):
            values = tuple(parse_java_int(value) for value in values)
        elif not all(
            isinstance(value, int) and not isinstance(value, bool) for value in values
        ):
            raise TypeError("Expected three ints or three strings (Java overloads)")
        return "W-37-" + "-".join(_format(value) for value in values) + "-00000"

    def prepareSendFlightWarningsCommand(self, *args):
        if len(args) == 1:
            return _warning_command(1, args[0])
        if len(args) == 2:
            bank, warnings = args
            return _warning_command(java_int(bank) + 32, warnings, bank)
        raise TypeError("Expected (warnings) or (bank, warnings)")

    def prepareSendFreeFallWarningsCommand(self, bank, warnings):
        return _warning_command(java_int(bank) + 3, warnings, bank)

    def prepareSendCanopyWarningsCommand(self, bank, warnings):
        return _warning_command(java_int(bank) + 9, warnings, bank)

    def prepareSendFreeFallSoundSetupCommand(self, pitch, volume):
        return _sound("02", pitch, volume)

    def prepareSendCanopySoundSetupCommand(self, pitch, volume):
        return _sound("08", pitch, volume)

    def prepareSendFlightWarningsSoundSetupCommand(self, pitch, volume):
        return _sound("31", pitch, volume)

    def prepareSendFreeFallPlaySoundCommand(self):
        return "W-19-00000-00000-00001-00000"

    def prepareSendCanopyPlaySoundCommand(self):
        return "W-19-00000-00000-00000-00001"

    def prepareSendFlightAlarmsPlaySoundCommand(self):
        return "W-19-00000-00001-00001-00001"

    def prepareSetDefaultAlarmValuesCommand(self):
        return "Factory Warnings Default"

    def prepareFactoryResetCommand(self):
        return "Factory Default"

    def prepareReadDeviceSettingsR40Command(self):
        return "R-40"

    def prepareReadDeviceSettingsR41Command(self):
        return "R-41"

    def prepareReadDeviceSettingsR42Command(self):
        return "R-42"

    def prepareDeviceSettingsW40Command(self, mode, beeps, diveType, temperatureUnits):
        return f"W-40-{_enum(mode, DeviceBLEMode):05d}-{_boolean(beeps)}-{_enum(diveType, DeviceDiveType):05d}-{_enum(temperatureUnits, DeviceTemperatureUnits):05d}"

    def prepareWriteDeviceSettingsW41Command(self, tapToEnableBLE, flatLine):
        tap = _boolean(tapToEnableBLE)
        return f"W-41-{_boolean(flatLine)}-{tap}-00000-00000"

    def prepareDeviceSettingsW42Command(
        self, backlightValue, dateTime, showTimeUnderCanopy, lcdTimeOut
    ):
        _enum(dateTime, DateFormat)
        backlight = _format(backlightValue)
        timeout = _format(lcdTimeOut)
        return f"W-42-{0 if dateTime == DateFormat.EU else 1:05d}-{timeout}-{_boolean(showTimeUnderCanopy)}-{backlight}"

    def prepareBacklightCommand(self, backlight, backlightValue):
        _boolean(backlight)
        java_int(backlightValue)
        return (
            f"Backlight On {_format(backlightValue, 2)}"
            if backlight
            else "Backlight Off"
        )

    def prepareMotionAlarmCommand(self, countdown, sensitivity):
        return f"Enable Motion {_format(countdown, 3)} {_format(sensitivity, 3)}"

    def prepareSetSwoopGuideCommand(self, checked):
        return f"W-21-00000-00000-00000-{_boolean(checked)}"

    def prepareSetTrackGuideCommand(self, checked):
        return f"W-21-00000-00000-00000-{_boolean(checked)}"

    def prepareSetCanopyActiveBankCommand(self, bankIndex):
        return _bank("23", bankIndex, "canopy")

    def prepareSetFlightWarningActiveBankCommand(self, bankIndex):
        return _bank("30", bankIndex, "flight warnings")

    def prepareSetFreeFallActiveBankCommand(self, bankIndex):
        return _bank("22", bankIndex, "free fall")

    def prepareSendAltitudeCommand(self, altitude, sign):
        java_int(altitude, 64)
        java_int(sign)
        if 0 <= altitude < 65001:
            return f"W-17-00000-00000-{0 if sign >= 0 else 1:05d}-{altitude:05d}"
        logging.getLogger(__name__).error("Wrong altitude:%s", altitude)
        return None

    def prepareReadJumpCountCommand(self):
        return CONSTANTS["READ_JUMP_COUNTER_COMMAND"]

    def prepareSetJumpCountCommand(self, count):
        return f"Set Jump Counter {_format(count)}"

    def prepareEraseEntireLogbookCommand(self):
        return "Erase Logbook"

    def prepareGetACCCommand(self, jumpNumberArg, startTime, durationArg):
        return f"Get xACC {_format(jumpNumberArg)} {_format(startTime, 3)} {_format(durationArg, 3)}"

    def prepareGetACCCommandHex(self, jumpNumberArg, startTime, durationArg):
        return f"Get Hex xACC {_format(jumpNumberArg)} {_format(startTime, 3)} {_format(durationArg, 3)}"

    def prepareGetDeviceInfoCommand(self):
        return "Who?"

    def prepareLoadLumpProfileCommandHex(self, jumpNumber):
        return f"Get Hex Profile in Jump {_format(jumpNumber)}"


for _name, _value in CONSTANTS.items():
    setattr(JavaUARTCommandBuilder, _name, _value)
JavaUARTCommandBuilder.Companion = JavaUARTCommandBuilder
JavaUARTCommandBuilder.INSTANCE = JavaUARTCommandBuilder()

# Signature manifest, used by JSON CLI adapters, transport permissions and audits.
# Flight warnings and freefall time each represent two Java overloads.
SIGNATURES = {
    "prepareDateTimeCommand": [("datetime",)],
    "preparePowerOffCommand": [()],
    "prepareSetDistanceUOM": [(DistanceUOM,)],
    "prepareSetSpeedUOM": [(SpeedUOM,)],
    "prepareGetSpeedUOM": [()],
    "prepareSetTotalFreeFallTimeCommand": [
        ("int", "int", "int"),
        ("string", "string", "string"),
    ],
    "prepareSendFlightWarningsCommand": [("warnings",), ("int", "warnings")],
    "prepareSendFreeFallWarningsCommand": [("int", "warnings")],
    "prepareSendCanopyWarningsCommand": [("int", "warnings")],
    "prepareSendFreeFallSoundSetupCommand": [("int", "int")],
    "prepareSendCanopySoundSetupCommand": [("int", "int")],
    "prepareSendFlightWarningsSoundSetupCommand": [("int", "int")],
    "prepareSendFreeFallPlaySoundCommand": [()],
    "prepareSendCanopyPlaySoundCommand": [()],
    "prepareSendFlightAlarmsPlaySoundCommand": [()],
    "prepareSetDefaultAlarmValuesCommand": [()],
    "prepareFactoryResetCommand": [()],
    "prepareReadDeviceSettingsR40Command": [()],
    "prepareReadDeviceSettingsR41Command": [()],
    "prepareReadDeviceSettingsR42Command": [()],
    "prepareDeviceSettingsW40Command": [
        (DeviceBLEMode, "bool", DeviceDiveType, DeviceTemperatureUnits)
    ],
    "prepareWriteDeviceSettingsW41Command": [("bool", "bool")],
    "prepareDeviceSettingsW42Command": [("int", DateFormat, "bool", "int")],
    "prepareBacklightCommand": [("bool", "int")],
    "prepareMotionAlarmCommand": [("int", "int")],
    "prepareSetSwoopGuideCommand": [("bool",)],
    "prepareSetTrackGuideCommand": [("bool",)],
    "prepareSetCanopyActiveBankCommand": [("int",)],
    "prepareSetFlightWarningActiveBankCommand": [("int",)],
    "prepareSetFreeFallActiveBankCommand": [("int",)],
    "prepareSendAltitudeCommand": [("long", "int")],
    "prepareReadJumpCountCommand": [()],
    "prepareSetJumpCountCommand": [("int",)],
    "prepareEraseEntireLogbookCommand": [()],
    "prepareGetACCCommand": [("int", "int", "int")],
    "prepareGetACCCommandHex": [("int", "int", "int")],
    "prepareGetDeviceInfoCommand": [()],
    "prepareLoadLumpProfileCommandHex": [("int",)],
}
READ_METHODS = {
    name
    for name in SIGNATURES
    if name.startswith(("prepareGet", "prepareRead", "prepareLoad"))
}
DESTRUCTIVE_METHODS = {
    "prepareFactoryResetCommand",
    "prepareEraseEntireLogbookCommand",
    "prepareSetJumpCountCommand",
}


def adapt_json_arguments(method, arguments):
    """Convert CLI JSON to Java-compatible values without coercing strings/ints."""
    if method not in SIGNATURES or not isinstance(arguments, list):
        raise ValueError("Expected a known Java method and a JSON array of arguments")
    for signature in SIGNATURES[method]:
        if len(signature) != len(arguments):
            continue
        try:
            result = []
            for kind, value in zip(signature, arguments):
                if kind in ("int", "long"):
                    result.append(java_int(value, 64 if kind == "long" else 32))
                elif kind == "string":
                    if not isinstance(value, str):
                        raise TypeError("Expected string")
                    result.append(value)
                elif kind == "bool":
                    _boolean(value)
                    result.append(value)
                elif kind == "warnings":
                    if value is not None and (
                        not isinstance(value, list)
                        or any(
                            item is not None and not isinstance(item, str)
                            for item in value
                        )
                    ):
                        raise TypeError("Expected a list of strings")
                    result.append(value)
                elif kind == "datetime":
                    result.append(datetime.fromisoformat(value))
                else:
                    result.append(kind[value])
            return result
        except (ValueError, TypeError, KeyError):
            continue
    raise ValueError(f"Arguments do not match Java signatures for {method}")
