"""Desktop session and staged settings, independent of the GUI toolkit.

All device operations belong to one asyncio loop. Editing a Draft never sends.
Only explicitly applied, validated changes are written, then read back.
"""

import asyncio
import logging
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial

from jumptrack import (
    JumpTrack,
    parse_battery_information,
    parse_jump_list,
    parse_settings_record,
    parse_warning_configuration,
    scan_devices,
    validate_flatline_cutoff,
)
from profile_decoder import parse_profile

logger = logging.getLogger(__name__)


CONFIRMATIONS = {"erase-logbook": "ERASE LOGBOOK", "factory-reset": "FACTORY RESET"}


@dataclass
class Snapshot:
    address: str
    details: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    jumps: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)


@dataclass
class ApplyResult:
    snapshot: Snapshot
    verified: list = field(default_factory=list)
    error: str = ""
    connected: bool = True


class Draft:
    def __init__(self, snapshot):
        self.snapshot = deepcopy(snapshot)
        self.pending = {}

    def set(self, key, value):
        if key not in self.snapshot.values:
            raise ValueError("This setting is unavailable on the connected device")
        validate_change(key, value)
        if value == self.snapshot.values[key]:
            self.pending.pop(key, None)
        else:
            self.pending[key] = value

    def value(self, key):
        return self.pending.get(key, self.snapshot.values.get(key))

    def reconcile(self, snapshot):
        pending = deepcopy(self.pending)
        self.snapshot = deepcopy(snapshot)
        self.pending = {
            key: value
            for key, value in pending.items()
            if snapshot.values.get(key) != value
        }

    def discard(self):
        self.pending.clear()


def validate_change(key, value):
    if key in ("distance_unit", "speed_unit", "warnings.canopy.guide"):
        allowed = (0, 1)
    elif re.fullmatch(r"settings\.(40|41|42)\.[0-3]", key):
        group, index = map(int, key.split(".")[1:])
        from jumptrack import SETTINGS_ALLOWED

        allowed = (0,) if (group, index) == (41, 0) else SETTINGS_ALLOWED[group][index]
        if group == 41 and index > 1:
            raise ValueError("Reserved fields cannot be edited")
    elif re.fullmatch(r"warnings\.(freefall|canopy|flight)\.bank\.[1-4]", key):
        if (
            not isinstance(value, tuple)
            or len(value) != 4
            or any(type(v) is not int or not 0 <= v <= 2147483647 for v in value)
        ):
            raise ValueError(
                "A warning bank requires four nonnegative integer altitudes"
            )
        return
    elif re.fullmatch(
        r"warnings\.(freefall|canopy|flight)\.(pitch|volume|active_bank)", key
    ):
        allowed = range(
            1, {"pitch": 8, "volume": 11, "active_bank": 5}[key.split(".")[-1]]
        )
    else:
        raise ValueError("Unsupported setting")
    if type(value) is not int or value not in allowed:
        raise ValueError("Setting value is outside its supported range")


def records(raw):
    result = {}
    for line in raw.splitlines():
        match = re.fullmatch(r"W-([0-9]{2})-((?:[0-9]{5,}-){3}[0-9]{5,})", line.strip())
        if match:
            result[int(match[1])] = tuple(map(int, match[2].split("-")))
    return result


class DeviceSession:
    sound_playback_seconds = 25

    def __init__(self, factory=JumpTrack, progress=None):
        self.factory = factory
        self.device = None
        self.address = None
        self.progress = progress or (lambda _message: None)
        self.needs_reload = False

    @property
    def connected(self):
        return self.device is not None and bool(self.device.client.is_connected)

    async def scan(self, *, all_devices=False, query=""):
        return await scan_devices(timeout=10, all_devices=all_devices, query=query)

    async def connect(self, address):
        await self.disconnect()
        self.device = self.factory(
            address=address, allow_writes=False, allow_destructive=False
        )
        self.address = address
        try:
            await self.device.connect()
            return await self.read_snapshot()
        except Exception:
            await self.disconnect()
            raise

    async def disconnect(self):
        device, self.device = self.device, None
        self.address = None
        if device is not None:
            await device.disconnect()

    def require_connected(self):
        if not self.connected:
            raise ConnectionError(
                "Device disconnected. Reconnect and reload before continuing."
            )

    async def read_snapshot(self, baseline=None, *, keys=None):
        self.require_connected()
        snapshot = (
            deepcopy(baseline) if baseline is not None else Snapshot(self.address)
        )
        requests = [
            ("Device information", self.device.get_device_info),
            ("Jump count", self.device.get_jump_counter),
            ("Jump list", self.device.get_jump_list),
            ("Warnings", self.device.get_all_warnings),
            ("Speed units", self.device.get_speed_uom),
            ("Settings 40", self.device.get_settings_40),
            ("Settings 41", self.device.get_settings_41),
            ("Settings 42", self.device.get_settings_42),
        ]
        if baseline is not None:
            # Applying preferences must not download the logbook again or probe
            # groups already reported as unsupported during connection.
            requests = [
                (label, call)
                for label, call in requests[3:]
                if not label.startswith("Settings ")
                or any(
                    key.startswith(f"settings.{label.split()[-1]}.")
                    for key in baseline.values
                )
            ]
        if keys is not None:
            labels = set()
            for key in keys:
                if key.startswith("warnings.") or key == "distance_unit":
                    labels.add("Warnings")
                elif key == "speed_unit":
                    labels.add("Speed units")
                elif key.startswith("settings."):
                    labels.add("Settings " + key.split(".")[1])
                    if key == "settings.41.0":
                        labels.add("Warnings")
            requests = [(label, call) for label, call in requests if label in labels]
        # A failed request stops the operation without closing the session.
        for label, call in requests:
            self.progress("Reading " + label.lower() + "…")
            snapshot.raw[label] = await call()
        snapshot.values.clear()
        snapshot.errors.clear()
        snapshot.details["device"] = snapshot.raw["Device information"].strip()
        snapshot.details["jump_count"] = snapshot.raw["Jump count"].strip()
        snapshot.jumps = sorted(
            parse_jump_list(snapshot.raw["Jump list"]),
            key=lambda r: r["jump_number"],
            reverse=True,
        )
        all_records = records(snapshot.raw["Warnings"])
        snapshot.details["battery_info"] = parse_battery_information(
            snapshot.raw["Warnings"]
        )
        snapshot.details.pop("altitude_offset", None)
        snapshot.details.pop("datetime", None)
        offset = all_records.get(17)
        if offset and offset[2] in (0, 1):
            snapshot.details["altitude_offset"] = offset[3] * (-1 if offset[2] else 1)
        clock = all_records.get(18)
        if clock:
            try:
                snapshot.details["datetime"] = datetime(
                    clock[3],
                    clock[2] % 100,
                    clock[2] // 1000,
                    clock[1],
                    clock[0] % 100,
                    clock[0] // 1000,
                ).isoformat()
            except ValueError:
                snapshot.errors["Clock"] = "Unrecognized device date/time"
        if 16 in all_records and all_records[16][3] in (0, 1):
            snapshot.values["distance_unit"] = all_records[16][3]
        speed = records(snapshot.raw["Speed units"]).get(38)
        if speed and speed[3] in (0, 1):
            snapshot.values["speed_unit"] = speed[3]
        if 37 in all_records:
            snapshot.details["freefall_total"] = ":".join(
                f"{v:02d}" for v in all_records[37][:3]
            )
        try:
            warnings = parse_warning_configuration(snapshot.raw["Warnings"])
            if warnings["guide_enabled"] is not None:
                snapshot.values["warnings.canopy.guide"] = warnings["guide_enabled"]
            snapshot.details["battery"] = warnings["battery"] or "Not reported"
            for category, config in warnings["categories"].items():
                for bank, altitudes in config["banks"].items():
                    if altitudes is not None:
                        snapshot.values[f"warnings.{category}.bank.{bank}"] = tuple(
                            altitudes
                        )
                for key in ("pitch", "volume", "active_bank"):
                    value = config[key]
                    if value is not None:
                        name = f"warnings.{category}.{key}"
                        try:
                            validate_change(name, value)
                            snapshot.values[name] = value
                        except ValueError:
                            snapshot.errors[name] = "Unrecognized device value"
        except ValueError as exc:
            snapshot.errors["Warnings"] = str(exc)
        for group in (40, 41, 42):
            try:
                values = parse_settings_record(snapshot.raw[f"Settings {group}"], group)
                for index, value in enumerate(values):
                    if group != 41 or index < 2:
                        snapshot.values[f"settings.{group}.{index}"] = value
            except ValueError as exc:
                snapshot.errors[f"Settings {group}"] = str(exc)
        if baseline is None:
            self.needs_reload = False
        return snapshot

    async def profile(self, number):
        self.require_connected()
        self.progress(f"Reading jump {number} profile…")
        raw = await self.device.get_jump_profile_hex(number)
        parsed = parse_profile(raw)
        if parsed["jump_number"] != number:
            raise ValueError("Returned profile does not match the selected jump")
        return {"raw": raw, "profile": parsed}

    async def reload_settings(self, baseline):
        """Recover by reading only; never replay an uncertain write."""
        snapshot = await self.read_snapshot(baseline)
        self.needs_reload = False
        return snapshot

    async def set_clock(self, baseline, value):
        self.require_connected()
        if (
            baseline.address != self.address
            or not isinstance(value, datetime)
            or value.tzinfo is not None
        ):
            raise ValueError("Use a local date/time for the connected device")
        device = self.device
        try:
            device.allow_writes = True
            await device.set_datetime(value)
            snapshot = await self.read_snapshot(baseline, keys=["distance_unit"])
            reported = snapshot.details.get("datetime")
            if (
                reported is None
                or abs((datetime.fromisoformat(reported) - value).total_seconds()) > 5
            ):
                raise ValueError(
                    "Time command sent, but device clock readback was not verified. Reload to inspect; no retry sent."
                )
            return snapshot
        finally:
            device.allow_writes = False

    async def test_sound(self, baseline, category):
        self.require_connected()
        if (
            category not in ("flight", "freefall", "canopy")
            or baseline.address != self.address
        ):
            raise ValueError("Invalid sound category or connected device")
        if self.needs_reload:
            raise ValueError("Reload device values before testing sound")
        if any(
            f"warnings.{category}.{name}" not in baseline.values
            for name in ("pitch", "volume")
        ):
            raise ValueError("Sound settings were not loaded for this device")
        device = self.device
        try:
            device.allow_writes = True
            await device.play_sound(category, wait_for_response=False)
        finally:
            device.allow_writes = False
        self.progress(
            f"{category.capitalize()} sound test sent; waiting for playback to finish…"
        )
        await asyncio.sleep(self.sound_playback_seconds)

    async def set_offset(self, baseline, value, phrase):
        self.require_connected()
        unit = baseline.values.get("distance_unit")
        if (
            baseline.address != self.address
            or phrase != "SET OFFSET"
            or type(value) is not int
            or unit not in (0, 1)
        ):
            raise ValueError("Offset confirmation, device or units are invalid")
        if abs(value) > (9900 if unit == 0 else 3000):
            raise ValueError("Offset exceeds the Android app's limits")
        fresh = await self.read_snapshot(baseline, keys=["distance_unit"])
        if fresh.values.get("distance_unit") != unit:
            raise ValueError("Device units changed; reload before setting offset")
        device = self.device
        try:
            device.allow_writes = True
            await device.set_altitude(
                abs(value), negative=value < 0, wait_for_response=False
            )
        finally:
            device.allow_writes = False
            await self.disconnect()

    def plan(self, snapshot, changes):
        values = snapshot.values | changes
        plan = []
        for group in (40, 41, 42):
            keys = [key for key in changes if key.startswith(f"settings.{group}.")]
            if not keys:
                continue
            v = [
                values[f"settings.{group}.{i}"] for i in range(2 if group == 41 else 4)
            ]
            if group == 40:
                kwargs = {
                    "ble_mode": ("automatic", "economy")[v[0]],
                    "beeps": bool(v[1]),
                    "dive_type": ("default", "3_seconds", "slow", "super_slow")[v[2]],
                    "temperature_unit": ("celsius", "fahrenheit")[v[3]],
                }
            elif group == 41:
                kwargs = {"flatline_cutoff": v[0], "tap_to_enable_ble": bool(v[1])}
            else:
                kwargs = {
                    "date_format": ("eu", "us")[v[0]],
                    "lcd_timeout": v[1],
                    "show_time_under_canopy": bool(v[2]),
                    "backlight_value": v[3],
                }
            plan.append(
                (keys, partial(getattr(self.device, f"set_settings_{group}"), **kwargs))
            )
        for category in ("freefall", "canopy", "flight"):
            for bank in range(1, 5):
                key = f"warnings.{category}.bank.{bank}"
                if key in changes:
                    call = (
                        partial(
                            self.device.set_flight_warnings,
                            list(values[key]),
                            bank=bank,
                        )
                        if category == "flight"
                        else partial(
                            getattr(self.device, f"set_{category}_warnings"),
                            bank,
                            list(values[key]),
                        )
                    )
                    plan.append(([key], call))
            keys = [
                f"warnings.{category}.{name}"
                for name in ("pitch", "volume")
                if f"warnings.{category}.{name}" in changes
            ]
            if keys:
                plan.append(
                    (
                        keys,
                        partial(
                            self.device.set_sound,
                            category,
                            values[f"warnings.{category}.pitch"],
                            values[f"warnings.{category}.volume"],
                        ),
                    )
                )
            key = f"warnings.{category}.active_bank"
            if key in changes:
                plan.append(
                    ([key], partial(self.device.set_active_bank, category, values[key]))
                )
        if "warnings.canopy.guide" in changes:
            plan.append(
                (
                    ["warnings.canopy.guide"],
                    partial(
                        self.device.set_swoop_guide,
                        bool(values["warnings.canopy.guide"]),
                    ),
                )
            )
        # Unit changes come last, never together with warning edits.
        for key, call, choices in [
            ("distance_unit", self.device.set_distance_uom, ("feet", "meters")),
            ("speed_unit", self.device.set_speed_uom, ("mph", "kmh")),
        ]:
            if key in changes:
                plan.append(([key], partial(call, choices[values[key]])))
        return plan

    async def apply(self, baseline, changes):
        self.require_connected()
        if self.needs_reload:
            raise ValueError(
                "Reload device values before applying again; the previous write was not verified."
            )
        if baseline.address != self.address:
            raise ValueError("Changes belong to a different device")
        changes = deepcopy(changes)
        for key, value in changes.items():
            if key not in baseline.values:
                raise ValueError("Cannot write a setting that was not loaded")
            validate_change(key, value)
        if "distance_unit" in changes and any(
            key.startswith("warnings.") or key == "settings.41.0" for key in changes
        ):
            raise ValueError(
                "Apply distance-unit changes separately, reload, then edit warning values."
            )
        bank_changes = any(".bank." in key for key in changes)
        if bank_changes and "distance_unit" not in baseline.values:
            raise ValueError(
                "Warning altitude units were not loaded; cannot safely edit banks."
            )
        fresh = await self.read_snapshot(baseline, keys=changes)
        if (
            bank_changes
            and fresh.values.get("distance_unit") != baseline.values["distance_unit"]
        ):
            return ApplyResult(
                fresh,
                error="Device altitude units changed. Review warning values in the newly loaded units.",
            )
        conflict = [
            key
            for key, value in changes.items()
            if key not in fresh.values
            or (
                fresh.values[key] != baseline.values[key] and fresh.values[key] != value
            )
        ]
        if conflict:
            return ApplyResult(
                fresh,
                error="Device values changed since loading. Review pending edits before applying again.",
            )
        remaining = {
            key: value for key, value in changes.items() if fresh.values[key] != value
        }
        if "settings.41.0" in changes:
            # W-41 is applied before warning edits, so validate against the current bank.
            bank = fresh.values.get("warnings.freefall.active_bank")
            altitudes = fresh.values.get(f"warnings.freefall.bank.{bank}")
            validate_flatline_cutoff(
                changes["settings.41.0"],
                fresh.values.get("distance_unit"),
                altitudes[3] if altitudes else None,
            )
        verified = [key for key in changes if key not in remaining]
        device = self.device
        try:
            plan = self.plan(fresh, remaining)
            device.allow_writes = True
            for index, (keys, call) in enumerate(plan, start=1):
                self.progress(f"Applying and verifying change {index} of {len(plan)}…")
                await call()
                fresh = await self.read_snapshot(fresh, keys=keys)
                if any(fresh.values.get(key) != changes[key] for key in keys):
                    self.needs_reload = True
                    return ApplyResult(
                        fresh,
                        verified,
                        "Readback did not match. Remaining edits were not sent; review the device.",
                    )
                verified.extend(keys)
            return ApplyResult(fresh, verified)
        except Exception as exc:
            logger.exception("Desktop apply interrupted; no retry will be sent")
            self.needs_reload = True
            connected = self.connected
            return ApplyResult(
                fresh,
                verified,
                f"{exc}\nA change may have applied. No retry was sent. "
                + (
                    "Reload device values before applying again."
                    if connected
                    else "Reconnect to review."
                ),
                connected,
            )
        finally:
            device.allow_writes = False

    async def destructive(self, action, phrase, address):
        self.require_connected()
        if (
            action not in CONFIRMATIONS
            or phrase != CONFIRMATIONS[action]
            or address != self.address
        ):
            raise ValueError(
                "Destructive confirmation does not match this action and device"
            )
        device = self.device
        try:
            device.allow_destructive = True
            self.progress("Performing explicitly confirmed action…")
            await getattr(
                device,
                {"erase-logbook": "erase_logbook", "factory-reset": "factory_reset"}[
                    action
                ],
            )()
        except Exception as exc:
            logger.exception("Confirmed destructive action returned an error")
            raise RuntimeError(
                f"{exc}\nThe action may have applied. No retry was sent. Reconnect to verify device state."
            ) from exc
        finally:
            device.allow_destructive = False
            await self.disconnect()
