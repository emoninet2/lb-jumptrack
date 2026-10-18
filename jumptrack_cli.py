"""CLI command definitions shared by help, dispatch, offline previews and docs."""
from dataclasses import dataclass, field
from datetime import datetime
import json
from java_uart_command_builder import (
    SIGNATURES, READ_METHODS, DESTRUCTIVE_METHODS, adapt_json_arguments,
)


@dataclass
class Operation:
    method: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    write: bool = False
    destructive: bool = False


# Simple zero-argument commands: CLI name, Python method, help text, access.
SIMPLE = (
    ('info', 'get_device_info', 'Read device information', 'read'),
    ('jump-counter', 'get_jump_counter', 'Read jump counter', 'read'),
    ('jump-list', 'get_jump_list', 'Read jump list', 'read'),
    ('warnings', 'get_all_warnings', 'Read all warning settings (R-00)', 'read'),
    ('speed-unit', 'get_speed_uom', 'Read speed units (R-38)', 'read'),
    ('settings-40', 'get_settings_40', 'Read BLE, beeps, dive and temperature settings', 'read'),
    ('settings-41', 'get_settings_41', 'Read tap-to-enable-BLE and flat-line settings', 'read'),
    ('settings-42', 'get_settings_42', 'Read display settings', 'read'),
    ('power-off', 'power_off', 'Power off the device', 'write'),
    ('default-alarms', 'set_default_alarm_values', 'Restore default alarm values', 'write'),
    ('erase-logbook', 'erase_logbook', 'Erase the entire logbook', 'destructive'),
    ('factory-reset', 'factory_reset', 'Restore factory defaults', 'destructive'),
)


def on_off(value):
    return value == 'on'


def bounded(low, high):
    def parse(value):
        import argparse
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('expected an integer')
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f'expected {low}–{high}')
        return number
    return parse


def add_commands(parser):
    sub = parser.add_subparsers(dest='action', title='commands', metavar='COMMAND')
    sub.add_parser('constants', help='List all Java master constants (offline)')
    direct = sub.add_parser('java', help='Call an original Java method with a JSON argument array')
    direct.add_argument('java_method', choices=tuple(SIGNATURES))
    direct.add_argument('arguments', nargs='?', default='[]', help='JSON array; enums use Java member names')
    direct.add_argument('--timeout', type=bounded(1, 3600), default=30)
    direct.set_defaults(method='execute_java', access='read')
    for name, method, help_text, access in SIMPLE:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(method=method, access=access)

    def command(name, method, help_text, access='write'):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(method=method, access=access)
        return p

    p = command('profile', 'get_jump_profile_hex', 'Read a hex jump profile', 'read')
    p.add_argument('jump_number', type=bounded(-2147483648, 2147483647))
    p.add_argument('--timeout', type=bounded(1, 3600), default=90, help='Response timeout in seconds (default: 90)')
    p = command('acc', 'get_acc', 'Read ACC data in hex or text', 'read')
    p.add_argument('jump_number', type=bounded(-2147483648, 2147483647))
    p.add_argument('start_time', type=bounded(-2147483648, 2147483647))
    p.add_argument('duration', type=bounded(-2147483648, 2147483647))
    p.add_argument('--format', choices=('hex', 'text'), default='hex')
    p.add_argument('--timeout', type=bounded(1, 3600), default=90)
    p = command('beeps', 'set_button_beeps', 'Change only button beeps; read back to verify')
    p.add_argument('enabled', choices=('on', 'off'))
    p = command('set-datetime', 'set_datetime', 'Set device wall-clock time (ISO datetime or now)')
    p.add_argument('value', help='Example: 2026-10-18T14:30:00 or now')
    for name, method, choices in (
        ('set-distance-unit', 'set_distance_uom', ('feet', 'meters')),
        ('set-speed-unit', 'set_speed_uom', ('mph', 'kmh')),
    ):
        p = command(name, method, 'Set ' + name[4:].replace('-', ' '))
        p.add_argument('unit', choices=choices)
    p = command('set-freefall-time', 'set_total_freefall_time', 'Set total freefall time')
    for key in ('hours', 'minutes', 'seconds'):
        p.add_argument(key, type=bounded(-2147483648, 2147483647))
    p = command('set-warnings', 'warnings_by_category', 'Set warning altitudes using Java list rules')
    p.add_argument('category', choices=('freefall', 'canopy', 'flight'))
    p.add_argument('values', nargs='+', help='Numeric strings: Java uses four values only for length 4; otherwise first three')
    p.add_argument('--bank', type=bounded(-2147483648, 2147483647), help='Required for freefall/canopy; omit for legacy flight W-01')
    p = command('set-sound', 'set_sound', 'Set category pitch and volume')
    p.add_argument('category', choices=('freefall', 'canopy', 'flight'))
    p.add_argument('pitch', type=bounded(-2147483648, 2147483647))
    p.add_argument('volume', type=bounded(-2147483648, 2147483647))
    p = command('play-sound', 'play_sound', 'Play a category sound')
    p.add_argument('category', choices=('freefall', 'canopy', 'flight'))
    p = command('set-settings-40', 'set_settings_40', 'Replace all four W-40 fields')
    p.add_argument('--ble-mode', required=True, choices=('automatic', 'economy'))
    p.add_argument('--beeps', dest='setting_beeps', required=True, choices=('on', 'off'))
    p.add_argument('--dive-type', required=True, choices=('default', '3_seconds', 'slow', 'super_slow'))
    p.add_argument('--temperature-unit', required=True, choices=('celsius', 'fahrenheit'))
    p = command('set-settings-41', 'set_settings_41', 'Replace W-41 fields; reserved fields are set to zero')
    p.add_argument('--tap-to-enable-ble', required=True, choices=('on', 'off'))
    p.add_argument('--flat-line', required=True, choices=('on', 'off'))
    p = command('set-settings-42', 'set_settings_42', 'Replace all four display settings fields')
    p.add_argument('--backlight-value', required=True, type=bounded(-2147483648, 2147483647))
    p.add_argument('--date-format', required=True, choices=('eu', 'us'))
    p.add_argument('--show-time-under-canopy', required=True, choices=('on', 'off'))
    p.add_argument('--lcd-timeout', required=True, type=bounded(-2147483648, 2147483647))
    p = command('backlight', 'set_backlight', 'Turn backlight on/off')
    p.add_argument('enabled', choices=('on', 'off'))
    p.add_argument('--value', type=bounded(-2147483648, 2147483647), default=0)
    p = command('motion-alarm', 'enable_motion_alarm', 'Enable motion alarm with countdown and sensitivity')
    p.add_argument('countdown', type=bounded(-2147483648, 2147483647))
    p.add_argument('sensitivity', type=bounded(-2147483648, 2147483647))
    for name, method in (('swoop-guide', 'set_swoop_guide'), ('track-guide', 'set_track_guide')):
        p = command(name, method, 'Turn ' + name.replace('-', ' ') + ' on/off (both use W-21)')
        p.add_argument('enabled', choices=('on', 'off'))
    p = command('set-active-bank', 'set_active_bank', 'Select an active warning bank')
    p.add_argument('category', choices=('freefall', 'canopy', 'flight'))
    p.add_argument('bank', type=bounded(-2147483648, 2147483647))
    p = command('set-altitude', 'set_altitude', 'Set altitude magnitude and optional negative sign')
    p.add_argument('altitude', type=bounded(-9223372036854775808, 9223372036854775807))
    sign = p.add_mutually_exclusive_group()
    sign.add_argument('--negative', action='store_true')
    sign.add_argument('--sign', type=bounded(-2147483648, 2147483647), help='Java sign argument: negative selects minus; zero/positive selects plus')
    p = command('set-jump-counter', 'set_jump_counter', 'Replace jump counter', 'destructive')
    p.add_argument('count', type=bounded(-2147483648, 2147483647))
    return sub


def operation(args):
    """Resolve parsed arguments without connecting to Bluetooth."""
    method = args.method
    kwargs = {}
    positional = ()
    if args.action == 'java':
        parsed = json.loads(args.arguments)
        adapted = adapt_json_arguments(args.java_method, parsed)
        return Operation('execute_java', (args.java_method, *adapted), {'timeout': args.timeout},
                         args.java_method not in READ_METHODS and args.java_method not in DESTRUCTIVE_METHODS,
                         args.java_method in DESTRUCTIVE_METHODS)
    if args.action == 'set-warnings':
        method = {'flight': 'set_flight_warnings', 'freefall': 'set_freefall_warnings', 'canopy': 'set_canopy_warnings'}[args.category]
        if args.category == 'flight':
            positional, kwargs = (args.values,), {'bank': args.bank}
        else:
            if args.bank is None:
                raise ValueError('--bank is required for freefall and canopy warnings')
            positional = (args.bank, args.values)
    elif method == 'get_jump_profile_hex':
        positional, kwargs = (args.jump_number,), {'timeout': args.timeout}
    elif method == 'get_acc':
        positional = (args.jump_number, args.start_time, args.duration)
        kwargs = {'hex_format': args.format == 'hex', 'timeout': args.timeout}
    elif method == 'set_datetime':
        value = datetime.now() if args.value == 'now' else datetime.fromisoformat(args.value)
        if value.tzinfo is not None:
            raise ValueError('Use a local wall-clock datetime without a timezone offset')
        positional = (value,)
    elif method in ('set_distance_uom', 'set_speed_uom'):
        positional = (args.unit,)
    elif method == 'set_total_freefall_time':
        positional = (args.hours, args.minutes, args.seconds)
    elif method == 'set_sound':
        positional = (args.category, args.pitch, args.volume)
    elif method == 'play_sound':
        positional = (args.category,)
    elif method == 'set_settings_40':
        kwargs = dict(ble_mode=args.ble_mode, beeps=on_off(args.setting_beeps), dive_type=args.dive_type, temperature_unit=args.temperature_unit)
    elif method == 'set_settings_41':
        kwargs = dict(tap_to_enable_ble=on_off(args.tap_to_enable_ble), flat_line=on_off(args.flat_line))
    elif method == 'set_settings_42':
        kwargs = dict(backlight_value=args.backlight_value, date_format=args.date_format, show_time_under_canopy=on_off(args.show_time_under_canopy), lcd_timeout=args.lcd_timeout)
    elif method == 'set_backlight':
        positional = (on_off(args.enabled), args.value)
    elif method == 'enable_motion_alarm':
        positional = (args.countdown, args.sensitivity)
    elif method in ('set_swoop_guide', 'set_track_guide', 'set_button_beeps'):
        positional = (on_off(args.enabled),)
    elif method == 'set_active_bank':
        positional = (args.category, args.bank)
    elif method == 'set_altitude':
        positional, kwargs = (args.altitude,), {'negative': args.sign < 0 if args.sign is not None else args.negative}
    elif method == 'set_jump_counter':
        positional = (args.count,)
    return Operation(method, positional, kwargs, args.access == 'write', args.access == 'destructive')


def preview(op, builder):
    if op.method == 'execute_java':
        method, *args = op.args
        return getattr(builder, method)(*args)
    if op.method == 'set_button_beeps':
        return 'R-40 -> preserve current fields, change beep flag -> W-40 -> R-40 verification (requires live settings)'
    kwargs = {key: value for key, value in op.kwargs.items() if key != 'timeout'}
    return getattr(builder, op.method)(*op.args, **kwargs)
