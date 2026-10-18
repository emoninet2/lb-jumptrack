"""Unofficial JumpTrack BLE client, based on JumpTrack UARTCommandBuilder.

Install: pip install bleak
Run: python jumptrack.py
Optional: python jumptrack.py --profile 35

Default runs are read-only. Explicit setting commands change configuration.
Destructive subcommands require --allow-destructive.
The app's response parsing and checksum algorithm are not included in the
command-builder source; returned values are raw device responses.
"""

import argparse
import asyncio
import re
import json
import os
from pathlib import Path
from datetime import datetime
from bleak import BleakClient
from bleak.exc import BleakError
from uart_command_builder import UARTCommandBuilder
from java_uart_command_builder import SIGNATURES, READ_METHODS, DESTRUCTIVE_METHODS

_ADDRESS_FILE = Path(__file__).with_name('.jumptrack-address')
ADDRESS = os.environ.get('JUMPTRACK_ADDRESS') or (
    _ADDRESS_FILE.read_text(encoding='utf-8').strip() if _ADDRESS_FILE.exists() else None
)
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
OUTPUT_DIR = Path("jumptrack_data")

# Families with dedicated initialization flows in the decompiled JumpTrack app.
# This is NOT a claim that every model in a family supports the same BLE commands.
SUPPORTED_DEVICE_FAMILIES = ("PROTRACK", "STELLA", "ORDINAL", "VISOX")
VERIFIED_PYTHON_MODELS = ("PROTRACK 3",)


def normalize_device_family(name):
    """Return a JumpTrack-recognized family or raise ValueError.

    Accepts family names and model names beginning with a family name,
    e.g. 'PROTRACK 3'. This checks names, not actual BLE compatibility.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Device name must be a nonempty string")
    normalized = " ".join(name.upper().split())
    for family in SUPPORTED_DEVICE_FAMILIES:
        if normalized == family or normalized.startswith(family + " "):
            return family
    raise ValueError(
        f"Unknown JumpTrack device family: {name!r}. "
        f"Recognized families: {', '.join(SUPPORTED_DEVICE_FAMILIES)}"
    )


def is_verified_python_model(name):
    """Whether this exact model has been tested with this Python client."""
    return isinstance(name, str) and " ".join(name.upper().split()) in VERIFIED_PYTHON_MODELS



class JumpTrack:
    def __init__(self, address=ADDRESS, *, allow_writes=False, allow_destructive=False, debug=False):
        address = address or ADDRESS
        if not address:
            raise ValueError("Set --address, JUMPTRACK_ADDRESS, or a local .jumptrack-address file")
        self.commands = UARTCommandBuilder()
        self.client = BleakClient(address)
        self.buffer = bytearray()
        self.response_event = asyncio.Event()
        self.command_lock = asyncio.Lock()
        self.allow_writes = allow_writes
        self.allow_destructive = allow_destructive
        self.debug = debug
        self._notifications_started = False

    def _notification_handler(self, _sender, data):
        self.buffer.extend(data)
        if self.debug:
            print(f"RX HEX: {bytes(data).hex(' ')}")
        if b"EOF\r\n" in self.buffer:
            self.response_event.set()

    async def connect(self):
        await self.client.connect()
        try:
            await self.client.start_notify(UART_TX, self._notification_handler)
            self._notifications_started = True
        except Exception:
            await self.client.disconnect()
            raise
        print("Connected to JumpTrack device")

    async def disconnect(self):
        try:
            if self.client.is_connected and self._notifications_started:
                await self.client.stop_notify(UART_TX)
        finally:
            self._notifications_started = False
            if self.client.is_connected:
                await self.client.disconnect()
            print("Disconnected")

    async def send_command(self, command, *, timeout=30, write=False, destructive=False):
        """Send an ASCII command; return raw decoded response.

        Raises TimeoutError instead of silently returning incomplete data.
        Some control commands may not use EOF; those need separate verification.
        """
        if command is None:
            raise ValueError("Java master returned null: no command was sent")
        if destructive and not self.allow_destructive:
            raise PermissionError("Destructive commands disabled; pass allow_destructive=True explicitly")
        if write and not self.allow_writes:
            raise PermissionError("Configuration commands disabled; pass allow_writes=True explicitly")
        if not self.client.is_connected:
            raise ConnectionError("Not connected")
        if not isinstance(command, str) or not command.isascii() or "\r" in command or "\n" in command:
            raise ValueError("Command must be one ASCII line without CR/LF")
        async with self.command_lock:
            self.buffer.clear()
            self.response_event.clear()
            payload = command.encode("ascii") + b"\r"
            print(f"Sending: {payload!r}")
            await self.client.write_gatt_char(UART_RX, payload, response=False)
            try:
                await asyncio.wait_for(self.response_event.wait(), timeout)
            except asyncio.TimeoutError as exc:
                partial = self.buffer.decode("utf-8", errors="replace")
                raise TimeoutError(f"No EOF after {timeout}s for {command!r}. Partial response:\n{partial}") from exc
            return self.buffer.decode("utf-8", errors="replace")

    async def execute_java(self, method, *args, timeout=30):
        """Send any original Java-named command using its declared access policy."""
        if method not in SIGNATURES:
            raise ValueError(f"Unknown Java method: {method}")
        command = getattr(self.commands, method)(*args)
        if command is None:
            return None  # Java null is a no-command result; never send it.
        return await self.send_command(
            command, timeout=timeout,
            write=method not in READ_METHODS and method not in DESTRUCTIVE_METHODS,
            destructive=method in DESTRUCTIVE_METHODS)

    # Read-only: device and logbook
    async def get_device_info(self):
        return await self.send_command(self.commands.get_device_info(), timeout=10)

    async def get_jump_counter(self):
        return await self.send_command(self.commands.get_jump_counter(), timeout=10)

    async def get_jump_list(self):
        return await self.send_command(self.commands.get_jump_list())

    async def get_all_warnings(self):
        return await self.send_command(self.commands.get_all_warnings())

    async def get_warning_configuration(self):
        """Read R-00 and return parsed warning settings alongside the raw response."""
        raw = await self.get_all_warnings()
        return parse_warning_configuration(raw)

    async def get_speed_uom(self):
        return await self.send_command(self.commands.get_speed_uom())

    async def get_settings_40(self):
        return await self.send_command(self.commands.get_settings_40())

    async def get_settings_41(self):
        return await self.send_command(self.commands.get_settings_41())

    async def get_settings_42(self):
        return await self.send_command(self.commands.get_settings_42())

    async def get_jump_profile_hex(self, jump_number, *, timeout=90):
        return await self.send_command(self.commands.get_jump_profile_hex(jump_number), timeout=timeout)

    async def get_acc(self, jump_number, start_time, duration, *, hex_format=True, timeout=90):
        return await self.send_command(self.commands.get_acc(jump_number, start_time, duration, hex_format=hex_format), timeout=timeout)

    # Configuration methods: disabled unless allow_writes=True
    async def _write(self, command, *, timeout=30):
        return await self.send_command(command, timeout=timeout, write=True)

    async def set_datetime(self, value: datetime):
        return await self._write(self.commands.set_datetime(value))

    async def power_off(self):
        return await self._write(self.commands.power_off())

    async def set_distance_uom(self, unit):
        return await self._write(self.commands.set_distance_uom(unit))

    async def set_speed_uom(self, unit):
        return await self._write(self.commands.set_speed_uom(unit))

    async def set_total_freefall_time(self, hours, minutes, seconds):
        return await self._write(self.commands.set_total_freefall_time(hours, minutes, seconds))

    async def set_flight_warnings(self, values, *, bank=None):
        return await self._write(self.commands.set_flight_warnings(values, bank=bank))

    async def set_freefall_warnings(self, bank, values):
        return await self._write(self.commands.set_freefall_warnings(bank, values))

    async def set_canopy_warnings(self, bank, values):
        return await self._write(self.commands.set_canopy_warnings(bank, values))

    async def set_sound(self, category, pitch, volume):
        return await self._write(self.commands.set_sound(category, pitch, volume))

    async def play_sound(self, category):
        return await self._write(self.commands.play_sound(category))

    async def set_default_alarm_values(self):
        return await self._write(self.commands.set_default_alarm_values())

    async def set_settings_40(self, *, ble_mode, beeps, dive_type, temperature_unit):
        return await self._write(self.commands.set_settings_40(ble_mode=ble_mode, beeps=beeps, dive_type=dive_type, temperature_unit=temperature_unit))

    async def set_button_beeps(self, enabled):
        """Read, change only W-40's beep field, then verify by reading back."""
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        if not self.allow_writes:
            raise PermissionError("Configuration commands disabled; pass allow_writes=True explicitly")
        current = parse_settings_40(await self.get_settings_40())
        if current[1] == int(enabled):
            return f"Button beeps already {'on' if enabled else 'off'}."
        updated = [*current]
        updated[1] = int(enabled)
        command = "W-40-" + "-".join(f"{value:05d}" for value in updated)
        try:
            await self._write(command)
        except TimeoutError as exc:
            raise TimeoutError(
                "Beep command was sent, but its response timed out; the change may "
                "have applied. No retry was sent. Read R-40 to check the device."
            ) from exc
        verified = parse_settings_40(await self.get_settings_40())
        if verified != updated:
            raise RuntimeError(f"W-40 verification mismatch: expected {updated}, received {verified}")
        return f"Button beeps {'on' if enabled else 'off'} (verified by R-40)."

    async def set_settings_41(self, *, tap_to_enable_ble, flat_line):
        return await self._write(self.commands.set_settings_41(tap_to_enable_ble=tap_to_enable_ble, flat_line=flat_line))

    async def set_settings_42(self, *, backlight_value, date_format, show_time_under_canopy, lcd_timeout):
        return await self._write(self.commands.set_settings_42(backlight_value=backlight_value, date_format=date_format, show_time_under_canopy=show_time_under_canopy, lcd_timeout=lcd_timeout))

    async def set_backlight(self, enabled, value=0):
        return await self._write(self.commands.set_backlight(enabled, value))

    async def enable_motion_alarm(self, countdown, sensitivity):
        return await self._write(self.commands.enable_motion_alarm(countdown, sensitivity))

    async def set_swoop_guide(self, enabled):
        return await self._write(self.commands.set_swoop_guide(enabled))

    async def set_track_guide(self, enabled):
        # The APK produces the same command as set_swoop_guide.
        return await self._write(self.commands.set_track_guide(enabled))

    async def set_active_bank(self, category, bank):
        return await self._write(self.commands.set_active_bank(category, bank))

    async def set_altitude(self, altitude, *, negative=False):
        return await self._write(self.commands.set_altitude(altitude, negative=negative))

    # Destructive: require allow_destructive=True
    async def _destructive(self, command):
        return await self.send_command(command, destructive=True)

    async def set_jump_counter(self, count):
        return await self._destructive(self.commands.set_jump_counter(count))

    async def erase_logbook(self):
        return await self._destructive(self.commands.erase_logbook())

    async def factory_reset(self):
        return await self._destructive(self.commands.factory_reset())


def _java_client_method(name):
    async def invoke(self, *args, timeout=30):
        return await self.execute_java(name, *args, timeout=timeout)
    invoke.__name__ = name
    invoke.__doc__ = f"Async transport for Java {name}; None means no command was sent."
    return invoke


for _java_name in SIGNATURES:
    setattr(JumpTrack, _java_name, _java_client_method(_java_name))


def parse_settings_40(raw):
    """Accept one complete W-40 record; reject unknown layouts before writing."""
    if not isinstance(raw, str) or not re.search(r"(?m)^EOF\s*$", raw):
        raise ValueError("Incomplete R-40 response; no settings changed")
    records = [line.strip() for line in raw.splitlines() if line.strip().startswith("W-40")]
    if len(records) != 1 or not re.fullmatch(r"W-40-(?:\d{5}-){3}\d{5}", records[0]):
        raise ValueError("Expected exactly one W-40 settings record; cannot preserve other settings")
    values = list(map(int, records[0].split("-")[2:]))
    if any(value not in allowed for value, allowed in zip(values, ((0, 1), (0, 1), (0, 1, 2, 3), (0, 1)))):
        raise ValueError("Unrecognized W-40 settings values; refusing to rewrite them")
    return values


def parse_jump_list(raw):
    """Extract observed rows; expose the profile count field and preserve old aliases."""
    records = []
    for line in raw.splitlines():
        parts = line.strip().split(",")
        if len(parts) == 8 and all(re.fullmatch(r"\d+", part) for part in parts):
            number, year, month, day, hour, minute, unknown_1, unknown_2 = map(int, parts)
            records.append({
                "jump_number": number,
                "timestamp": datetime(year, month, day, hour, minute).isoformat(),
                "profile_count_field": unknown_1,
                "unknown_1": unknown_1,  # Compatibility alias; inclusive convention unresolved.
                "unknown_2": unknown_2,
            })
    return records


def parse_warning_configuration(raw):
    """Parse observed PROTRACK 3 R-00 records without changing device settings.

    Pitch/volume are category-wide, not per individual altitude threshold.
    A zero threshold is preserved as zero (its meaning is not assumed).
    Altitude units are not inferred from W-16; consult device configuration.
    """
    if not isinstance(raw, str):
        raise TypeError("R-00 response must be a string")
    if not re.search(r"(?m)^R-00\s*$", raw):
        raise ValueError("Response does not appear to be R-00")
    if not re.search(r"(?m)^EOF\s*$", raw):
        raise ValueError("R-00 response is incomplete (missing EOF)")

    records = {}
    for line in raw.splitlines():
        match = re.fullmatch(r"W-(\d{2})-((?:\d{5}-){3}\d{5})", line.strip())
        if match:
            code = int(match.group(1))
            values = [int(value) for value in match.group(2).split("-")]
            # W-19 appears multiple times for sound tests; not needed here.
            if code != 19:
                records[code] = values

    categories = {}
    for name, sound_code, active_code, active_bank_code, bank_codes in (
        ("freefall", 2, 3, 22, range(4, 8)),
        ("canopy", 8, 9, 23, range(10, 14)),
        ("flight", 31, 32, 30, range(33, 37)),
    ):
        sound = records.get(sound_code)
        active_bank_record = records.get(active_bank_code)
        active_bank = active_bank_record[3] if active_bank_record else None
        categories[name] = {
            "pitch": sound[2] if sound else None,
            "volume": sound[3] if sound else None,
            "active_bank": active_bank,
            "active_warning_altitudes": records.get(active_code),
            "banks": {
                str(index): records.get(code)
                for index, code in enumerate(bank_codes, start=1)
            },
        }
    battery = re.search(r"(?m)^Battery:\s*(.+)$", raw)
    return {
        "categories": categories,
        "altitude_unit": "unverified",
        "battery": battery.group(1).strip() if battery else None,
        "raw": raw,
    }


def format_warning_configuration(config):
    """Human-readable summary of parsed R-00 warning settings."""
    lines = ["JUMPTRACK WARNING CONFIGURATION", "=" * 40,
             "Altitude unit: not verified (values shown as transmitted)"]
    for name, info in config["categories"].items():
        lines.extend([
            "", name.upper(),
            f"  Active bank: {info['active_bank'] if info['active_bank'] is not None else 'unknown'}",
            f"  Pitch:       {info['pitch'] if info['pitch'] is not None else 'unknown'} / 7",
            f"  Volume:      {info['volume'] if info['volume'] is not None else 'unknown'} / 10",
            f"  Active thresholds: {info['active_warning_altitudes']}",
        ])
        for bank, altitudes in info["banks"].items():
            marker = " (selected)" if info["active_bank"] == int(bank) else ""
            lines.append(f"  Bank {bank}{marker}: {altitudes if altitudes is not None else 'not returned'}")
    if config["battery"]:
        lines.extend(["", f"Battery: {config['battery']}"])
    return "\n".join(lines)


def save_response(name, content):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(content, encoding="utf-8")
    print(f"Saved: {path.resolve()}")


def build_parser():
    from jumptrack_cli import add_commands
    parser = argparse.ArgumentParser(
        description="JumpTrack BLE client. Put global options before COMMAND.",
        epilog="Without COMMAND, read device info, jump counter and jump list. Use COMMAND --help for details.")
    parser.add_argument("--dry-run", action="store_true", help="Preview a subcommand without Bluetooth")
    parser.add_argument("--allow-destructive", action="store_true", help="Enable explicit erase/reset/counter subcommands")
    parser.add_argument("--output", type=Path, help="Save a subcommand response to this file")
    parser.add_argument("--beeps", choices=("on", "off"), help="Set button beeps, preserving other W-40 settings")
    parser.add_argument("--address", default=ADDRESS, help="BLE address or platform device identifier")
    parser.add_argument("--profile", type=int, help="Also download the specified jump profile")
    parser.add_argument("--settings", action="store_true", help="Also read R-00, R-38, R-40, R-41, R-42")
    parser.add_argument("--warnings", action="store_true", help="Read and display all warning banks, pitch, and volume")
    parser.add_argument("--debug", action="store_true", help="Print incoming BLE packets as hex")
    parser.add_argument("--list-devices", action="store_true", help="List JumpTrack-recognized families and verified Python models")
    add_commands(parser)
    return parser


async def run_operation(args, op):
    device = JumpTrack(address=args.address, debug=args.debug,
                       allow_writes=op.write, allow_destructive=op.destructive)
    try:
        await device.connect()
        result = await getattr(device, op.method)(*op.args, **op.kwargs)
        print(result)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result, encoding="utf-8")
            print(f"Saved: {args.output.resolve()}")
    finally:
        await device.disconnect()


async def main(argv=None):
    from jumptrack_cli import operation, preview
    parser = build_parser()
    args = parser.parse_args(argv)
    legacy_reads = args.settings or args.warnings or args.profile is not None
    if args.action == 'constants':
        if legacy_reads or args.beeps is not None or args.list_devices or args.output is not None or args.allow_destructive:
            parser.error("constants is an offline listing; do not combine it with device-operation flags")
        from java_uart_command_builder import CONSTANTS
        print(json.dumps(CONSTANTS, indent=2))
        return
    if args.action:
        if legacy_reads or args.beeps is not None or args.list_devices:
            parser.error("Use COMMAND separately from legacy read/beep/list flags")
        try:
            op = operation(args)
            command = preview(op, UARTCommandBuilder())
        except (ValueError, TypeError) as exc:
            parser.error(str(exc))
        if args.dry_run:
            print("null" if command is None else command)
            return
        if command is None:
            parser.error("Java master returned null for these inputs; no command was sent")
        if op.destructive and not args.allow_destructive:
            parser.error("This command requires --allow-destructive before COMMAND")
        try:
            await run_operation(args, op)
        except (TimeoutError, ConnectionError, ValueError, RuntimeError, OSError, BleakError) as exc:
            detail = str(exc)
            if isinstance(exc, TimeoutError) and (op.write or op.destructive):
                detail += "\nThe write may have applied; no retry was sent. Check the device before retrying."
            parser.exit(1, f"Error: {detail}\n")
        return
    if args.dry_run or args.output is not None or args.allow_destructive:
        parser.error("--dry-run, --output and --allow-destructive require a COMMAND")
    if args.list_devices:
        print("JumpTrack-recognized device families:")
        for family in SUPPORTED_DEVICE_FAMILIES:
            print(f"  - {family}")
        print("Verified with this Python client:")
        for model in VERIFIED_PYTHON_MODELS:
            print(f"  - {model}")
        return

    if not args.address:
        parser.error("Set --address or JUMPTRACK_ADDRESS before connecting")
    device = JumpTrack(address=args.address, debug=args.debug, allow_writes=args.beeps is not None)
    try:
        await device.connect()
        if args.beeps is not None:
            print(await device.set_button_beeps(args.beeps == "on"))
            if not (args.settings or args.warnings or args.profile is not None):
                return
        commands = [
            ("DEVICE INFORMATION", "device_info.txt", device.get_device_info),
            ("JUMP COUNTER", "jump_counter.txt", device.get_jump_counter),
            ("JUMP LIST", "jump_list.txt", device.get_jump_list),
        ]
        if args.warnings and not args.settings:
            commands.append(("ALL WARNINGS", "all_warnings.txt", device.get_all_warnings))
        if args.settings:
            commands.extend([
                ("ALL WARNINGS", "all_warnings.txt", device.get_all_warnings),
                ("SPEED UNITS", "speed_uom.txt", device.get_speed_uom),
                ("SETTINGS R-40", "settings_40.txt", device.get_settings_40),
                ("SETTINGS R-41", "settings_41.txt", device.get_settings_41),
                ("SETTINGS R-42", "settings_42.txt", device.get_settings_42),
            ])
        if args.profile is not None:
            commands.append((f"JUMP {args.profile} PROFILE", f"jump_{args.profile:05d}_profile.txt",
                             lambda: device.get_jump_profile_hex(args.profile)))
        for title, filename, func in commands:
            print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
            try:
                result = await func()
            except TimeoutError as exc:
                print(f"WARNING: {exc}")
                continue
            print(result)
            save_response(filename, result)
            if filename == "all_warnings.txt":
                try:
                    parsed = parse_warning_configuration(result)
                    summary = format_warning_configuration(parsed)
                    print("\n" + summary)
                    save_response("warning_configuration.txt", summary + "\n")
                    structured = {key: value for key, value in parsed.items() if key != "raw"}
                    save_response("warning_configuration.json", json.dumps(structured, indent=2) + "\n")
                except ValueError as exc:
                    print(f"WARNING: Could not parse R-00: {exc}")
            if filename == "jump_list.txt":
                print("Parsed jumps:", parse_jump_list(result))
    finally:
        await device.disconnect()


if __name__ == "__main__":
    asyncio.run(main())