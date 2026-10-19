"""Java-master command builder, with compatible Python-friendly aliases.

CamelCase methods preserve the master semantics, including null -> None.
Snake_case methods adapt names/enums and allow integer warning lists, then
call the same implementation. They add no field-width limits.
"""

from datetime import datetime

from java_uart_command_builder import (
    CONSTANTS,
    READ_ALL_WARNINGS_COMMAND,
    READ_JUMPS_LIST_COMMAND,
    DateFormat,
    DeviceBLEMode,
    DeviceDiveType,
    DeviceTemperatureUnits,
    DistanceUOM,
    JavaUARTCommandBuilder,
    SpeedUOM,
    java_int,
)


def _bool(value):
    if not isinstance(value, bool):
        raise TypeError("Expected boolean")
    return value


def _choice(value, choices, enum_type=None):
    if enum_type is not None and isinstance(value, enum_type):
        return value
    if not isinstance(value, str) or value.lower() not in choices:
        raise ValueError(f"Expected one of {', '.join(choices)}: {value!r}")
    return choices[value.lower()]


def _warnings(values):
    if values is None:
        return None
    return [
        str(java_int(value)) if isinstance(value, int) else value for value in values
    ]


class UARTCommandBuilder(JavaUARTCommandBuilder):
    """Build commands only; sending and response handling belong to JumpTrack."""

    def get_device_info(self):
        return self.prepareGetDeviceInfoCommand()

    def get_jump_counter(self):
        return self.prepareReadJumpCountCommand()

    def get_jump_list(self):
        return READ_JUMPS_LIST_COMMAND

    def get_all_warnings(self):
        return READ_ALL_WARNINGS_COMMAND

    def get_speed_uom(self):
        return self.prepareGetSpeedUOM()

    def get_settings_40(self):
        return self.prepareReadDeviceSettingsR40Command()

    def get_settings_41(self):
        return self.prepareReadDeviceSettingsR41Command()

    def get_settings_42(self):
        return self.prepareReadDeviceSettingsR42Command()

    def get_jump_profile_hex(self, jump_number):
        return self.prepareLoadLumpProfileCommandHex(jump_number)

    def get_acc(self, jump_number, start_time, duration, *, hex_format=True):
        return (
            self.prepareGetACCCommandHex(jump_number, start_time, duration)
            if _bool(hex_format)
            else self.prepareGetACCCommand(jump_number, start_time, duration)
        )

    def set_datetime(self, value: datetime):
        return self.prepareDateTimeCommand(value)

    def power_off(self):
        return self.preparePowerOffCommand()

    def set_distance_uom(self, unit):
        return self.prepareSetDistanceUOM(
            _choice(
                unit,
                {"feet": DistanceUOM.FEET, "meters": DistanceUOM.METERS},
                DistanceUOM,
            )
        )

    def set_speed_uom(self, unit):
        return self.prepareSetSpeedUOM(
            _choice(
                unit,
                {
                    "mph": SpeedUOM.MILE_HOUR,
                    "kmh": SpeedUOM.KILOMETER_HOUR,
                    "fps": SpeedUOM.FEET_SECONDS,
                    "mps": SpeedUOM.METER_SECOND,
                },
                SpeedUOM,
            )
        )

    def set_total_freefall_time(self, hours, minutes, seconds):
        return self.prepareSetTotalFreeFallTimeCommand(hours, minutes, seconds)

    def set_flight_warnings(self, values, *, bank=None):
        return (
            self.prepareSendFlightWarningsCommand(_warnings(values))
            if bank is None
            else self.prepareSendFlightWarningsCommand(bank, _warnings(values))
        )

    def set_freefall_warnings(self, bank, values):
        return self.prepareSendFreeFallWarningsCommand(bank, _warnings(values))

    def set_canopy_warnings(self, bank, values):
        return self.prepareSendCanopyWarningsCommand(bank, _warnings(values))

    def set_sound(self, category, pitch, volume):
        return _choice(
            category,
            {
                "freefall": self.prepareSendFreeFallSoundSetupCommand,
                "canopy": self.prepareSendCanopySoundSetupCommand,
                "flight": self.prepareSendFlightWarningsSoundSetupCommand,
            },
        )(pitch, volume)

    def play_sound(self, category):
        return _choice(
            category,
            {
                "freefall": self.prepareSendFreeFallPlaySoundCommand,
                "canopy": self.prepareSendCanopyPlaySoundCommand,
                "flight": self.prepareSendFlightAlarmsPlaySoundCommand,
            },
        )()

    def set_default_alarm_values(self):
        return self.prepareSetDefaultAlarmValuesCommand()

    def set_settings_40(self, *, ble_mode, beeps, dive_type, temperature_unit):
        return self.prepareDeviceSettingsW40Command(
            _choice(
                ble_mode,
                {
                    "automatic": DeviceBLEMode.AUTOMATIC,
                    "economy": DeviceBLEMode.ECONOMY,
                },
                DeviceBLEMode,
            ),
            beeps,
            _choice(
                dive_type,
                {
                    "default": DeviceDiveType.DEFAULT,
                    "3_seconds": DeviceDiveType._3_SECONDS,
                    "slow": DeviceDiveType.SLOW,
                    "super_slow": DeviceDiveType.SUPER_SLOW,
                },
                DeviceDiveType,
            ),
            _choice(
                temperature_unit,
                {
                    "celsius": DeviceTemperatureUnits.CELSIUS,
                    "fahrenheit": DeviceTemperatureUnits.FAHRENHEIT,
                },
                DeviceTemperatureUnits,
            ),
        )

    def set_settings_41(self, *, tap_to_enable_ble, flatline_cutoff):
        if type(flatline_cutoff) is not int or not 0 <= flatline_cutoff <= 1000:
            raise ValueError(
                "Flatline cutoff must be an integer altitude from 0 to 1000"
            )
        return f"W-41-{flatline_cutoff:05d}-{int(tap_to_enable_ble):05d}-00000-00000"

    def set_settings_42(
        self, *, backlight_value, date_format, show_time_under_canopy, lcd_timeout
    ):
        return self.prepareDeviceSettingsW42Command(
            backlight_value,
            _choice(
                date_format, {"eu": DateFormat.EU, "us": DateFormat.US}, DateFormat
            ),
            show_time_under_canopy,
            lcd_timeout,
        )

    def set_backlight(self, enabled, value=0):
        return self.prepareBacklightCommand(enabled, value)

    def enable_motion_alarm(self, countdown, sensitivity):
        return self.prepareMotionAlarmCommand(countdown, sensitivity)

    def set_swoop_guide(self, enabled):
        return self.prepareSetSwoopGuideCommand(enabled)

    def set_track_guide(self, enabled):
        return self.prepareSetTrackGuideCommand(enabled)

    def set_active_bank(self, category, bank):
        return _choice(
            category,
            {
                "canopy": self.prepareSetCanopyActiveBankCommand,
                "flight": self.prepareSetFlightWarningActiveBankCommand,
                "freefall": self.prepareSetFreeFallActiveBankCommand,
            },
        )(bank)

    def set_altitude(self, altitude, *, negative=False):
        return self.prepareSendAltitudeCommand(altitude, -1 if _bool(negative) else 0)

    def set_jump_counter(self, count):
        return self.prepareSetJumpCountCommand(count)

    def erase_logbook(self):
        return self.prepareEraseEntireLogbookCommand()

    def factory_reset(self):
        return self.prepareFactoryResetCommand()


UARTCommandBuilder.Companion = UARTCommandBuilder
UARTCommandBuilder.INSTANCE = UARTCommandBuilder()
globals().update(CONSTANTS)
