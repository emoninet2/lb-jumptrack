"""Explicitly synthetic desktop demo: no Bluetooth objects or hardware writes."""

import binascii
from datetime import datetime
from types import SimpleNamespace

from gui_backend import DeviceSession


def response(prefix, body=""):
    data = prefix + "\r\n" + (body + "\r\n" if body else "")
    return (
        data
        + f"CheckSum.Bytes: {len(data.encode()):05d}\r\nCheckSum.Sum: {binascii.crc_hqx(data.encode(), 0):05d}\r\nEOF\r\n"
    )


def record(code, values):
    return f"W-{code:02d}-" + "-".join(f"{v:05d}" for v in values)


class DemoDevice:
    def __init__(self, address, allow_writes=False, allow_destructive=False):
        self.address = address
        self.allow_writes = allow_writes
        self.allow_destructive = allow_destructive
        self.client = SimpleNamespace(is_connected=False)
        self.groups = {40: [0, 0, 0, 0], 41: [0, 1, 0, 0], 42: [0, 30, 1, 50]}
        self.distance = 0
        self.speed = 0
        self.guide = 0
        self.offset = 0
        self.clock = datetime(2026, 9, 27, 17, 38, 0)
        self.jumps = [35, 34, 33]
        self.banks = {
            category: {
                bank: (
                    (0, 1200, 900, 600)
                    if category == "canopy"
                    else (6000, 5000, 4000, 3000)
                    if category == "freefall"
                    else (0, 10000, 1500, 1000)
                )
                for bank in range(1, 5)
            }
            for category in ("freefall", "canopy", "flight")
        }
        self.sounds = {category: [4, 7] for category in self.banks}
        self.active = {category: 1 for category in self.banks}

    def writable(self):
        if not self.allow_writes:
            raise PermissionError("Demo changes require explicit Apply")

    async def connect(self):
        self.client.is_connected = True

    async def disconnect(self):
        self.client.is_connected = False

    async def get_device_info(self):
        return response(
            "Who?", "PROTRACK 3\r\nSynthetic demo device — no hardware connected"
        )

    async def get_jump_counter(self):
        return response("Get Jump Counter", record(39, (0, 0, 0, len(self.jumps))))

    async def get_jump_list(self):
        return response(
            "Get New Jump List",
            "\r\n".join(f"{n},2026,9,27,17,38,1001,15360" for n in self.jumps),
        )

    async def get_all_warnings(self):
        rows = []
        for cat, sound, active, bankbase, bankactive in [
            ("freefall", 2, 3, 4, 22),
            ("canopy", 8, 9, 10, 23),
            ("flight", 31, 32, 33, 30),
        ]:
            rows.extend(
                [
                    record(sound, (0, 0, *self.sounds[cat])),
                    record(active, self.banks[cat][self.active[cat]]),
                    record(bankactive, (0, 0, 0, self.active[cat])),
                ]
            )
            rows.extend(
                record(bankbase + bank - 1, vals)
                for bank, vals in self.banks[cat].items()
            )
        rows.extend(
            [
                record(21, (0, 0, 0, self.guide)),
                record(16, (0, 0, 0, self.distance)),
                record(17, (0, 0, int(self.offset < 0), abs(self.offset))),
                record(
                    18,
                    (
                        self.clock.second * 1000 + self.clock.minute,
                        self.clock.hour,
                        self.clock.day * 1000 + self.clock.month,
                        self.clock.year,
                    ),
                ),
                record(37, (12, 34, 56, 0)),
                "Battery: 5.4 Volt, 1",
            ]
        )
        return response("R-00", "\r\n".join(rows))

    async def get_speed_uom(self):
        return response("R-38", record(38, (0, 0, 0, self.speed)))

    async def get_settings_40(self):
        return response("R-40", record(40, self.groups[40]))

    async def get_settings_41(self):
        return response("R-41", record(41, self.groups[41]))

    async def get_settings_42(self):
        return response("R-42", record(42, self.groups[42]))

    async def set_settings_40(self, *, ble_mode, beeps, dive_type, temperature_unit):
        self.writable()
        self.groups[40] = [
            ("automatic", "economy").index(ble_mode),
            int(beeps),
            ("default", "3_seconds", "slow", "super_slow").index(dive_type),
            ("celsius", "fahrenheit").index(temperature_unit),
        ]

    async def set_settings_41(self, *, tap_to_enable_ble, flatline_cutoff):
        self.writable()
        self.groups[41] = [int(flatline_cutoff), int(tap_to_enable_ble), 0, 0]

    async def set_settings_42(
        self, *, backlight_value, date_format, show_time_under_canopy, lcd_timeout
    ):
        self.writable()
        self.groups[42] = [
            ("eu", "us").index(date_format),
            lcd_timeout,
            int(show_time_under_canopy),
            backlight_value,
        ]

    async def set_distance_uom(self, value):
        self.writable()
        self.distance = ("feet", "meters").index(value)

    async def set_datetime(self, value):
        self.writable()
        self.clock = value

    async def set_altitude(self, altitude, *, negative=False, wait_for_response=True):
        self.writable()
        self.offset = altitude * (-1 if negative else 1)
        self.client.is_connected = False

    async def set_speed_uom(self, value):
        self.writable()
        self.speed = ("mph", "kmh").index(value)

    async def set_freefall_warnings(self, bank, values):
        self.writable()
        self.banks["freefall"][bank] = tuple(values)

    async def set_canopy_warnings(self, bank, values):
        self.writable()
        self.banks["canopy"][bank] = tuple(values)

    async def set_flight_warnings(self, values, *, bank=None):
        self.writable()
        self.banks["flight"][bank] = tuple(values)

    async def set_sound(self, category, pitch, volume):
        self.writable()
        self.sounds[category] = [pitch, volume]

    async def play_sound(self, category, *, wait_for_response=True):
        self.writable()
        if category not in self.sounds:
            raise ValueError("Unknown sound category")

    async def set_swoop_guide(self, enabled):
        self.writable()
        self.guide = int(enabled)

    async def set_active_bank(self, category, bank):
        self.writable()
        self.active[category] = bank

    async def erase_logbook(self):
        if not self.allow_destructive:
            raise PermissionError("Destructive action not confirmed")
        self.jumps = []

    async def factory_reset(self):
        if not self.allow_destructive:
            raise PermissionError("Destructive action not confirmed")
        self.jumps = []
        self.groups[40] = [0, 0, 0, 0]

    async def get_jump_profile_hex(self, number):
        if number not in self.jumps:
            raise ValueError("Jump is not available in demo logbook")
        words = []
        for i in range(1000):
            time = -2 + i * 0.25
            altitude = (
                13600
                if time < 0
                else max(0, 13600 - time * 200)
                if time < 51
                else max(0, 3400 - (time - 51) * 18)
            )
            pressure = 1013.25 * (1 - altitude / (44330.8 * 3.2808)) ** (1 / 0.190263)
            words.append(round(pressure * 10))
        header = [
            number,
            10132,
            210,
            13600,
            3400,
            51,
            9,
            27,
            2026,
            17,
            38,
            122,
            12,
            134,
            18,
            len(words) + 1,
        ]
        return response(
            f"Get Hex Profile in Jump {number:05d}",
            "\r\n".join([*map(str, header), "".join(f"{v:04X}" for v in words)]),
        )


class DemoSession(DeviceSession):
    sound_playback_seconds = 0

    def __init__(self, progress=None):
        self.devices = {}
        super().__init__(factory=self._device, progress=progress)

    def _device(self, address, **permissions):
        if address not in self.devices:
            self.devices[address] = DemoDevice(address, **permissions)
        return self.devices[address]

    async def scan(self, *, all_devices=False, query=""):
        rows = [
            {
                "name": "PROTRACK 3 · Demo",
                "address": "DEMO-LOCAL",
                "rssi": -42,
                "family": "PROTRACK",
                "verified_model": False,
            }
        ]
        return [
            r
            for r in rows
            if not query
            or query.casefold() in (r["name"] + " " + r["address"]).casefold()
        ]
